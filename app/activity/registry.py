"""目前的活動與已載入的引擎（design.md D7）：同一時間最多只有一場準備中或搶答中的活動。"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..db import Database
from ..worksheet.store import WorksheetStore
from . import codes
from .engine import (
    ENDED,
    INTERRUPTED,
    LIVE_PHASES,
    PREPARING,
    ActivityEngine,
    ActivityInfo,
    Clock,
    TeamState,
    WallClock,
    utc_now,
)
from .errors import ActivityInProgress, ActivityInterrupted, InvalidInput, InvalidState, NotFound
from .repository import SqliteActivityRepository
from .units import build_units

logger = logging.getLogger("buzzer")

ACTIVITY_NOT_FOUND = "找不到活動"


class ActivityRegistry:
    """settings 需要 max_teams、team_name_max、max_answer_length、fairness_enabled、
    cooldown_seconds、cooldown_lead。"""

    def __init__(self, db: Database, worksheets: WorksheetStore, settings: Any, *,
                 clock: Clock = time.monotonic, wall: WallClock = utc_now) -> None:
        self.repo = SqliteActivityRepository(db)
        self.worksheets = worksheets
        self.settings = settings
        self.clock = clock
        self.wall = wall
        self._engines: dict[int, ActivityEngine] = {}
        self._latest: int | None = None

    def startup(self) -> int:
        count = self.repo.mark_unfinished_interrupted()
        if count:
            logger.info("伺服器啟動：%d 場未結束的活動已標示為已中斷", count)
        return count

    @property
    def latest(self) -> ActivityEngine | None:
        """本次啟動後最近建立的活動（老師的 WebSocket 快照用）。"""
        return self._engines.get(self._latest) if self._latest is not None else None

    @property
    def current(self) -> ActivityEngine | None:
        return next((e for e in self._engines.values() if e.phase in LIVE_PHASES), None)

    def _validate_teams(self, names: list[str]) -> list[str]:
        s = self.settings
        cleaned = [n.strip() for n in names]
        if not 1 <= len(cleaned) <= s.max_teams:
            raise InvalidInput(f"組數必須是 1–{s.max_teams} 組")
        for i, name in enumerate(cleaned, 1):
            if not name:
                raise InvalidInput(f"第 {i} 組的組名不可為空白")
            if len(name) > s.team_name_max:
                raise InvalidInput(f"第 {i} 組的組名超過 {s.team_name_max} 字")
        dupes = sorted({n for n in cleaned if cleaned.count(n) > 1})
        if dupes:
            raise InvalidInput("組名不可重複：" + "、".join(dupes))
        return cleaned

    def create(self, worksheet_id: int, team_names: list[str], fairness_enabled: bool | None,
               cooldown_seconds: int | None, cooldown_lead: int | None) -> ActivityEngine:
        if self.current is not None:
            raise ActivityInProgress()
        worksheet = self.worksheets.get(worksheet_id)
        if worksheet is None:
            raise NotFound("找不到學習單")
        names = self._validate_teams(team_names)
        s = self.settings
        fairness = s.fairness_enabled if fairness_enabled is None else fairness_enabled
        n = cooldown_seconds or s.cooldown_seconds
        k = cooldown_lead or s.cooldown_lead
        used: set[str] = set()
        teams = []
        for i, name in enumerate(names, 1):
            code = codes.new_code(used)
            used.add(code)
            teams.append(TeamState(i, name, codes.code_hash(code), 1, code))
        created_at = self.wall()
        activity_id = self.repo.create_activity(worksheet_id, PREPARING, fairness, n, k,
                                                created_at, teams)
        info = ActivityInfo(activity_id, worksheet_id, PREPARING, fairness, n, k, created_at)
        engine = ActivityEngine(info, build_units(worksheet.parsed), {t.id: t for t in teams},
                                self.repo, s.max_answer_length, clock=self.clock, wall=self.wall)
        self._engines[activity_id] = engine
        self._latest = activity_id
        logger.info("建立活動 %s：%d 組、%d 個搶答單位", activity_id, len(teams), len(engine.units))
        return engine

    def get(self, activity_id: int) -> ActivityEngine:
        """記憶體中的引擎；已結束但不在記憶體中（例如重啟後）的活動從資料庫載入。"""
        engine = self._engines.get(activity_id)
        if engine is not None:
            return engine
        info = self.repo.get_info(activity_id)
        if info is None:
            raise NotFound(ACTIVITY_NOT_FOUND)
        if info.phase == INTERRUPTED:
            raise ActivityInterrupted()
        if info.phase != ENDED:  # 資料庫中是進行中但記憶體沒有：不應發生，視同中斷
            raise ActivityInterrupted("活動已中斷，請老師重新建立活動")
        worksheet = self.worksheets.get(info.worksheet_id)
        if worksheet is None:
            raise InvalidState("找不到活動所使用的學習單")
        teams = self.repo.load_teams(info.id)
        engine = ActivityEngine(info, build_units(worksheet.parsed), {t.id: t for t in teams},
                                self.repo, self.settings.max_answer_length, clock=self.clock,
                                wall=self.wall, submissions=self.repo.load_submissions(info.id))
        self._engines[info.id] = engine
        return engine

    def phase_of(self, activity_id: int) -> str:
        engine = self._engines.get(activity_id)
        if engine is not None:
            return engine.phase
        info = self.repo.get_info(activity_id)
        if info is None:
            raise NotFound(ACTIVITY_NOT_FOUND)
        return info.phase

    def list(self) -> list[dict[str, Any]]:
        return [{"id": i.id, "worksheetId": i.worksheet_id, "phase": self.phase_of(i.id),
                 "createdAt": i.created_at.isoformat(),
                 "endedAt": i.ended_at.isoformat() if i.ended_at else None}
                for i in self.repo.list_all()]

    def find_team_by_code(self, code: str) -> tuple[ActivityEngine, TeamState] | None:
        """只在目前進行中的活動裡比對。"""
        engine = self.current
        if engine is None:
            return None
        team = engine.find_team_by_code(code)
        return (engine, team) if team else None
