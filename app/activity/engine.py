"""ActivityEngine：一場活動的判定核心（design.md D2–D4、D8）。

- 所有會改變狀態的操作都在同一把 asyncio.Lock 內依序執行，「伺服器處理順序」就是取得鎖的順序。
- 成功與否不另外保存，一律以結果契約推導：順位最小且未被判無效的那筆（D3）。
- 引擎不處理 HTTP 或 WebSocket，只回傳結果與事件；推播由 realtime 在鎖釋放後送出。
- 不依賴 FastAPI，可以單獨測試。
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from ..results.contract import (
    ActivityResult,
    ResultGroup,
    ResultRecord,
    ResultUnit,
    outcome_of,
    success_counts,
    winner_of,
)
from . import codes
from .errors import InvalidState, NotEnded, NotFound, PersistFailed, RejectReason, SubmissionRejected
from .units import BuzzUnit

logger = logging.getLogger("buzzer")

PREPARING = "preparing"
RUNNING = "running"
ENDED = "ended"
INTERRUPTED = "interrupted"
LIVE_PHASES = (PREPARING, RUNNING)

# 單位狀態
NO_SUBMISSION = "no_submission"   # 尚無人搶答
WON = "won"                       # 已搶答
OPEN = "open"                     # 搶答中、有送出但成功者已被判無效（重新開放）
NO_WINNER = "no_winner"           # 已結束且沒有成功者

Clock = Callable[[], float]
WallClock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ActivityInfo:
    id: int
    worksheet_id: int
    phase: str
    fairness_enabled: bool
    cooldown_seconds: int
    cooldown_lead: int
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None


@dataclass
class TeamState:
    id: int
    name: str
    code_hash: str
    code_version: int = 1
    code: str | None = field(default=None, repr=False)  # 明文只在記憶體，供老師畫面顯示


@dataclass
class Submission:
    id: int
    unit_key: str
    team_id: int
    answers: dict[int, str]
    rank: int
    received_at: datetime
    invalidated: bool = False
    invalidated_at: datetime | None = None

    def record(self) -> ResultRecord:
        return ResultRecord(rank=self.rank, group_id=self.team_id, answers=dict(self.answers),
                            invalidated=self.invalidated)


@dataclass
class Cooldown:
    until: float          # 單調時鐘
    trigger_id: int       # 觸發這次冷卻的送出


class ActivityRepository(Protocol):
    def update_phase(self, activity_id: int, phase: str, *, started_at: datetime | None = None) -> None: ...

    def persist_results(self, activity_id: int, submissions: list[Submission],
                        ended_at: datetime) -> None: ...

    def update_invalidation(self, activity_id: int, submission_id: int,
                            invalidated_at: datetime) -> None: ...

    def update_team_code(self, activity_id: int, team_id: int, code_hash: str,
                         code_version: int) -> None: ...


@dataclass(frozen=True)
class Event:
    """audience：teacher（老師）、team（team_id 那一組）、all（老師與該活動所有學生）、
    revoke（撤銷 team_id 那一組的連線）。payload 為 {"type": "snapshot"} 時，
    推播中心依每條連線的身分各自產生快照。"""

    audience: str
    payload: dict[str, Any]
    team_id: int | None = None


SNAPSHOT: dict[str, Any] = {"type": "snapshot"}


def _answers_json(answers: dict[int, str]) -> dict[str, str]:
    return {str(k): v for k, v in sorted(answers.items())}


class ActivityEngine:
    def __init__(self, info: ActivityInfo, units: list[BuzzUnit], teams: dict[int, TeamState],
                 repo: ActivityRepository, max_answer_length: int, *,
                 clock: Clock = time.monotonic, wall: WallClock = utc_now,
                 submissions: list[Submission] | None = None) -> None:
        self.info = info
        self.units = units
        self.teams = teams
        self.repo = repo
        self.max_answer_length = max_answer_length
        self.clock = clock
        self.wall = wall
        self.submissions: list[Submission] = list(submissions or [])
        self.cooldowns: dict[int, Cooldown] = {}
        self._units = {u.key: u for u in units}
        self._lock = asyncio.Lock()

    @property
    def id(self) -> int:
        return self.info.id

    @property
    def phase(self) -> str:
        return self.info.phase

    # ---------- 以結果契約推導 ----------

    def _unit_subs(self, key: str) -> list[Submission]:
        return sorted((s for s in self.submissions if s.unit_key == key), key=lambda s: s.rank)

    def _result_unit(self, unit: BuzzUnit) -> ResultUnit:
        return ResultUnit(unit.key, unit.question_nos,
                          tuple(s.record() for s in self._unit_subs(unit.key)))

    def _winner(self, key: str) -> Submission | None:
        winner = winner_of(self._result_unit(self._units[key]))
        if winner is None:
            return None
        return next(s for s in self.submissions if s.unit_key == key and s.rank == winner.rank)

    def _outcome(self, sub: Submission) -> str:
        unit = self._result_unit(self._units[sub.unit_key])
        return outcome_of(unit, sub.record())

    def to_result(self) -> ActivityResult:
        return ActivityResult(
            activity_id=self.id,
            worksheet_id=self.info.worksheet_id,
            ended_at=self.info.ended_at or self.info.created_at,
            groups=tuple(ResultGroup(t.id, t.name) for t in self.teams.values()),
            units=tuple(self._result_unit(u) for u in self.units),
        )

    def wins(self) -> dict[int, int]:
        return success_counts(self.to_result())

    def unit_status(self, key: str) -> str:
        if self._winner(key) is not None:
            return WON
        if self.phase == ENDED:
            return NO_WINNER
        return OPEN if self._unit_subs(key) else NO_SUBMISSION

    def cooldown_remaining(self, team_id: int) -> int:
        cd = self.cooldowns.get(team_id)
        if cd is None:
            return 0
        left = max(0, math.ceil(cd.until - self.clock()))
        if left == 0:
            del self.cooldowns[team_id]
        return left

    # ---------- 階段 ----------

    async def start(self) -> list[Event]:
        async with self._lock:
            if self.phase != PREPARING:
                raise InvalidState("只有準備中的活動可以開始搶答")
            if not self.units or not self.teams:
                raise InvalidState("至少需要 1 個搶答單位與 1 個組別才能開始")
            now = self.wall()
            self.repo.update_phase(self.id, RUNNING, started_at=now)
            self.info.phase, self.info.started_at = RUNNING, now
            logger.info("活動 %s 開始搶答", self.id)
            return [Event("all", {"type": "phaseChanged", "phase": RUNNING})]

    async def end(self) -> list[Event]:
        async with self._lock:
            if self.phase != RUNNING:
                raise InvalidState("只有搶答中的活動可以結束")
            now = self.wall()
            try:
                # 寫入成功後才改變階段
                self.repo.persist_results(self.id, self.submissions, now)
            except Exception as exc:
                logger.error("活動 %s 結果保存失敗 type=%s", self.id, type(exc).__name__)
                raise PersistFailed() from None
            self.info.phase, self.info.ended_at = ENDED, now
            self.cooldowns.clear()
            logger.info("活動 %s 已結束，共 %d 筆送出", self.id, len(self.submissions))
            return [Event("all", {"type": "phaseChanged", "phase": ENDED}), Event("all", SNAPSHOT)]

    # ---------- 送出（design.md D4） ----------

    async def submit(self, team_id: int, code_version: int, unit_key: str,
                     answers: dict[int, str]) -> tuple[dict[str, Any], list[Event]]:
        async with self._lock:
            if self.phase != RUNNING:                                          # 1
                raise SubmissionRejected(RejectReason.NOT_RUNNING)
            team = self.teams.get(team_id)
            if team is None or team.code_version != code_version:             # 2
                raise SubmissionRejected(RejectReason.CODE_OUTDATED)
            left = self.cooldown_remaining(team_id)                            # 3
            if left:
                raise SubmissionRejected(RejectReason.COOLDOWN, seconds=left)
            unit = self._units.get(unit_key)                                   # 4
            if unit is None:
                raise SubmissionRejected(RejectReason.UNKNOWN_UNIT)
            expected, given = set(unit.question_nos), set(answers)             # 5
            if expected != given:
                raise SubmissionRejected(RejectReason.INCOMPLETE_GROUP,
                                         missing=sorted(expected - given),
                                         unexpected=sorted(given - expected))
            cleaned: dict[int, str] = {}
            for no in unit.question_nos:                                       # 6
                text = answers[no].strip()
                if not text:
                    raise SubmissionRejected(RejectReason.INVALID_ANSWER, question_no=no,
                                             problem="不可為空白")
                if len(text) > self.max_answer_length:
                    raise SubmissionRejected(RejectReason.INVALID_ANSWER, question_no=no,
                                             problem=f"超過 {self.max_answer_length} 字")
                cleaned[no] = text
            existing = self._unit_subs(unit_key)
            if any(s.team_id == team_id for s in existing):                    # 7
                raise SubmissionRejected(RejectReason.ALREADY_SUBMITTED)
            sub = Submission(id=len(self.submissions) + 1, unit_key=unit_key, team_id=team_id,
                             answers=cleaned, rank=len(existing) + 1, received_at=self.wall())
            self.submissions.append(sub)
            outcome = self._outcome(sub)
            events = [
                Event("team", {"type": "teamSubmission", "unitKey": unit_key, "rank": sub.rank,
                               "outcome": outcome}, team_id),
                Event("teacher", {"type": "submission", "unitKey": unit_key, "teamId": team_id,
                                  "answers": _answers_json(cleaned), "rank": sub.rank,
                                  "outcome": outcome}),
            ]
            if outcome == "success":
                events += self._maybe_cooldown(team_id, sub.id)
            message = "搶答成功！" if outcome == "success" else f"未搶到，第 {sub.rank} 順位"
            return ({"unitKey": unit_key, "rank": sub.rank, "outcome": outcome,
                     "message": message}, events)

    def _maybe_cooldown(self, team_id: int, trigger_id: int) -> list[Event]:
        """即時送出成功後才檢查；成功數包含這次成功，最少成功數也包含自己。"""
        if not self.info.fairness_enabled:
            return []
        wins = self.wins()
        if wins[team_id] - min(wins.values()) < self.info.cooldown_lead:
            return []
        n = self.info.cooldown_seconds
        self.cooldowns[team_id] = Cooldown(self.clock() + n, trigger_id)
        return self._cooldown_events(team_id, True, n)

    @staticmethod
    def _cooldown_events(team_id: int, active: bool, seconds: int) -> list[Event]:
        payload = {"type": "cooldown", "teamId": team_id, "active": active,
                   "remainingSeconds": seconds}
        return [Event("team", payload, team_id), Event("teacher", payload)]

    # ---------- 判定無效與遞補 ----------

    async def invalidate(self, unit_key: str) -> tuple[dict[str, Any], list[Event]]:
        async with self._lock:
            if self.phase not in (RUNNING, ENDED):
                raise InvalidState("只有搶答中或已結束的活動可以判定無效")
            unit = self._units.get(unit_key)
            if unit is None:
                raise NotFound("找不到這個搶答單位")
            winner = self._winner(unit_key)
            if winner is None:
                raise InvalidState("這個搶答單位目前沒有成功者，無法判定無效")
            now = self.wall()
            if self.phase == ENDED:
                # 已結束：先寫入資料庫，成功後才更新記憶體
                self.repo.update_invalidation(self.id, winner.id, now)
            winner.invalidated, winner.invalidated_at = True, now
            successor = self._winner(unit_key)  # 順位最小的「未搶到」遞補；遞補不觸發冷卻
            events = [
                Event("team", {"type": "invalidated", "unitKey": unit_key,
                               "message": f"{unit.display}的答案已被老師判定無效"}, winner.team_id),
                Event("teacher", {"type": "invalidated", "unitKey": unit_key,
                                  "teamId": winner.team_id}),
            ]
            if successor is not None:
                events += [
                    Event("team", {"type": "promoted", "unitKey": unit_key,
                                   "message": f"{unit.display}遞補為搶答成功"}, successor.team_id),
                    Event("teacher", {"type": "promoted", "unitKey": unit_key,
                                      "teamId": successor.team_id}),
                ]
            cd = self.cooldowns.get(winner.team_id)
            if cd is not None and cd.trigger_id == winner.id:
                del self.cooldowns[winner.team_id]
                events += self._cooldown_events(winner.team_id, False, 0)
            status = self.unit_status(unit_key)
            logger.info("活動 %s 的單位 %s 判定無效（遞補：%s）", self.id, unit_key,
                        "有" if successor else "無")
            return ({"unitKey": unit_key, "invalidatedTeamId": winner.team_id,
                     "promotedTeamId": successor.team_id if successor else None,
                     "unitStatus": status}, events)

    # ---------- 組別代碼 ----------

    async def regenerate_code(self, team_id: int) -> tuple[str, list[Event]]:
        async with self._lock:
            if self.phase not in LIVE_PHASES:
                raise InvalidState("活動已結束或已中斷，不能重新產生代碼")
            team = self.teams.get(team_id)
            if team is None:
                raise NotFound("找不到這個組別")
            code = codes.new_code({t.code for t in self.teams.values() if t.code})
            digest, version = codes.code_hash(code), team.code_version + 1
            self.repo.update_team_code(self.id, team_id, digest, version)
            team.code, team.code_hash, team.code_version = code, digest, version
            logger.info("活動 %s 的組別 %d 重新產生代碼", self.id, team_id)
            return code, [Event("revoke", {"type": "sessionRevoked", "reason": "codeRegenerated"},
                                team_id)]

    def find_team_by_code(self, code: str) -> TeamState | None:
        digest = codes.code_hash(code)
        return next((t for t in self.teams.values() if t.code_hash == digest), None)

    # ---------- 檢視（依身分過濾） ----------

    def _unit_list(self) -> list[dict[str, Any]]:
        return [{"key": u.key, "display": u.display, "questionNos": list(u.question_nos)}
                for u in self.units]

    def _sub_json(self, s: Submission) -> dict[str, Any]:
        return {"id": s.id, "teamId": s.team_id, "teamName": self.teams[s.team_id].name,
                "answers": _answers_json(s.answers), "rank": s.rank, "outcome": self._outcome(s)}

    def view_for_teacher(self) -> dict[str, Any]:
        wins = self.wins()
        show_codes = self.phase in LIVE_PHASES
        return {
            "id": self.id,
            "worksheetId": self.info.worksheet_id,
            "phase": self.phase,
            "fairness": {"enabled": self.info.fairness_enabled,
                         "cooldownSeconds": self.info.cooldown_seconds,
                         "cooldownLead": self.info.cooldown_lead},
            "teams": [{"id": t.id, "name": t.name, "code": t.code if show_codes else None,
                       "wins": wins[t.id], "cooldownRemaining": self.cooldown_remaining(t.id)}
                      for t in self.teams.values()],
            "units": [{**u, "status": self.unit_status(u["key"]),
                       "submissions": [self._sub_json(s) for s in self._unit_subs(u["key"])]}
                      for u in self._unit_list()],
        }

    def view_for_team(self, team_id: int) -> dict[str, Any]:
        """結束前只含本組資料與單位清單（不含任何單位狀態）；結束後另含完整結果。"""
        team = self.teams[team_id]
        mine = [{"unitKey": s.unit_key, "rank": s.rank, "outcome": self._outcome(s),
                 "answers": _answers_json(s.answers)}
                for s in self.submissions if s.team_id == team_id]
        return {
            "activityId": self.id,
            "phase": self.phase,
            "team": {"id": team.id, "name": team.name},
            "cooldownRemaining": self.cooldown_remaining(team_id),
            "units": self._unit_list(),
            "mySubmissions": mine,
            "results": self.results_view(include_all=False) if self.phase == ENDED else None,
        }

    def results_view(self, include_all: bool) -> dict[str, Any]:
        if self.phase != ENDED:
            raise NotEnded()
        wins = self.wins()
        units = []
        for u in self._unit_list():
            winner = self._winner(u["key"])
            entry: dict[str, Any] = {
                **u,
                "status": WON if winner else NO_WINNER,
                "winner": ({"teamId": winner.team_id, "teamName": self.teams[winner.team_id].name,
                            "answers": _answers_json(winner.answers)} if winner else None),
            }
            if include_all:
                entry["submissions"] = [self._sub_json(s) for s in self._unit_subs(u["key"])]
            units.append(entry)
        return {"activityId": self.id, "units": units,
                "teams": [{"id": t.id, "name": t.name, "wins": wins[t.id]}
                          for t in self.teams.values()]}
