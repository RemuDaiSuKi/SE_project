"""搶答活動的 SQLite repository（design.md D7）。資料表只由本模組存取。

進行中的送出只存在記憶體；活動結束時才以一筆交易寫入。
"""

from __future__ import annotations

from datetime import datetime

from ..db import Database
from .engine import ENDED, INTERRUPTED, LIVE_PHASES, ActivityInfo, Submission, TeamState


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _info(row) -> ActivityInfo:  # noqa: ANN001
    return ActivityInfo(
        id=row["id"],
        worksheet_id=row["worksheet_id"],
        phase=row["phase"],
        fairness_enabled=bool(row["fairness_enabled"]),
        cooldown_seconds=row["cooldown_seconds"],
        cooldown_lead=row["cooldown_lead"],
        created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
        started_at=_dt(row["started_at"]),
        ended_at=_dt(row["ended_at"]),
    )


class SqliteActivityRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- 建立與查詢 ----

    def create_activity(self, worksheet_id: int, phase: str, fairness_enabled: bool,
                        cooldown_seconds: int, cooldown_lead: int, created_at: datetime,
                        teams: list[TeamState]) -> int:
        """寫入活動與組別；只保存代碼的 SHA-256，明文不寫入。回傳活動 ID。"""
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO activities (worksheet_id, phase, fairness_enabled, cooldown_seconds,"
                " cooldown_lead, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (worksheet_id, phase, int(fairness_enabled), cooldown_seconds, cooldown_lead,
                 _iso(created_at)))
            activity_id = int(cur.lastrowid)  # type: ignore[arg-type]
            conn.executemany(
                "INSERT INTO activity_teams (activity_id, team_id, name, code_hash, code_version)"
                " VALUES (?, ?, ?, ?, ?)",
                [(activity_id, t.id, t.name, t.code_hash, t.code_version) for t in teams])
        return activity_id

    def get_info(self, activity_id: int) -> ActivityInfo | None:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
        return _info(row) if row is not None else None

    def list_all(self) -> list[ActivityInfo]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT * FROM activities ORDER BY created_at DESC, id DESC").fetchall()
        return [_info(r) for r in rows]

    def load_teams(self, activity_id: int) -> list[TeamState]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT * FROM activity_teams WHERE activity_id = ? ORDER BY team_id",
                                (activity_id,)).fetchall()
        return [TeamState(r["team_id"], r["name"], r["code_hash"], r["code_version"]) for r in rows]

    def load_submissions(self, activity_id: int) -> list[Submission]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT * FROM activity_submissions WHERE activity_id = ? ORDER BY id",
                                (activity_id,)).fetchall()
            answers = conn.execute("SELECT * FROM activity_answers WHERE activity_id = ?",
                                   (activity_id,)).fetchall()
        by_sub: dict[int, dict[int, str]] = {}
        for a in answers:
            by_sub.setdefault(a["submission_id"], {})[a["question_no"]] = a["answer"]
        return [Submission(id=r["id"], unit_key=r["unit_key"], team_id=r["team_id"],
                           answers=dict(sorted(by_sub.get(r["id"], {}).items())), rank=r["rank"],
                           received_at=_dt(r["received_at"]),  # type: ignore[arg-type]
                           invalidated=bool(r["invalidated"]),
                           invalidated_at=_dt(r["invalidated_at"]))
                for r in rows]

    def mark_unfinished_interrupted(self) -> int:
        """伺服器啟動時：準備中、搶答中的活動一律改為已中斷。"""
        with self.db.transaction() as conn:
            cur = conn.execute(
                f"UPDATE activities SET phase = ? WHERE phase IN ({','.join('?' * len(LIVE_PHASES))})",
                (INTERRUPTED, *LIVE_PHASES))
            return cur.rowcount

    # ---- ActivityRepository（引擎使用） ----

    def update_phase(self, activity_id: int, phase: str, *, started_at: datetime | None = None) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE activities SET phase = ?, started_at = COALESCE(?, started_at)"
                         " WHERE id = ?", (phase, _iso(started_at), activity_id))

    def persist_results(self, activity_id: int, submissions: list[Submission],
                        ended_at: datetime) -> None:
        """一筆交易寫入全部送出並把階段改為已結束。"""
        with self.db.transaction() as conn:
            conn.executemany(
                "INSERT INTO activity_submissions (activity_id, id, unit_key, team_id, rank,"
                " invalidated, received_at, invalidated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(activity_id, s.id, s.unit_key, s.team_id, s.rank, int(s.invalidated),
                  _iso(s.received_at), _iso(s.invalidated_at)) for s in submissions])
            conn.executemany(
                "INSERT INTO activity_answers (activity_id, submission_id, question_no, answer)"
                " VALUES (?, ?, ?, ?)",
                [(activity_id, s.id, no, text) for s in submissions for no, text in s.answers.items()])
            conn.execute("UPDATE activities SET phase = ?, ended_at = ? WHERE id = ?",
                         (ENDED, _iso(ended_at), activity_id))

    def update_invalidation(self, activity_id: int, submission_id: int,
                            invalidated_at: datetime) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE activity_submissions SET invalidated = 1, invalidated_at = ?"
                         " WHERE activity_id = ? AND id = ?",
                         (_iso(invalidated_at), activity_id, submission_id))

    def update_team_code(self, activity_id: int, team_id: int, code_hash: str,
                         code_version: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE activity_teams SET code_hash = ?, code_version = ?"
                         " WHERE activity_id = ? AND team_id = ?",
                         (code_hash, code_version, activity_id, team_id))
