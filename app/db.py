"""SQLite 連線與 schema。"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 4

# 第 1 版以 .xlsx 原始檔為來源，沒有試算表 ID，無法轉換；升級時捨棄（design.md D8）
_DROP_V1 = """
DROP TABLE IF EXISTS worksheet_questions;
DROP TABLE IF EXISTS worksheet_groups;
DROP TABLE IF EXISTS worksheets;
"""

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS worksheets (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    spreadsheet_id   TEXT    NOT NULL,
    spreadsheet_url  TEXT    NOT NULL,
    title            TEXT    NOT NULL,
    label_no         TEXT    NOT NULL,
    label_question   TEXT    NOT NULL,
    label_answer     TEXT    NOT NULL,
    question_count   INTEGER NOT NULL,
    group_count      INTEGER NOT NULL,
    confirmed_at     TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS worksheet_groups (
    worksheet_id INTEGER NOT NULL REFERENCES worksheets(id) ON DELETE CASCADE,
    group_no     INTEGER NOT NULL,
    source_no    TEXT,
    sheet_id     INTEGER NOT NULL,
    sheet_name   TEXT    NOT NULL,
    range_ref    TEXT    NOT NULL,
    PRIMARY KEY (worksheet_id, group_no)
);
CREATE TABLE IF NOT EXISTS worksheet_questions (
    worksheet_id INTEGER NOT NULL REFERENCES worksheets(id) ON DELETE CASCADE,
    no           INTEGER NOT NULL,
    sheet_id     INTEGER NOT NULL,
    sheet_name   TEXT    NOT NULL,
    cell_ref     TEXT    NOT NULL,
    row          INTEGER NOT NULL,
    source_no    TEXT,
    sub_label    TEXT,
    group_no     INTEGER,
    PRIMARY KEY (worksheet_id, no)
);
"""

# 第 3 版：未確認的匯入預覽改存資料庫，沒有有效期限、重啟後仍可確認（與 SpecKit 組一致）。
# 只新增資料表，不動既有的學習單資料。
_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS worksheet_previews (
    preview_id       TEXT    PRIMARY KEY,
    spreadsheet_id   TEXT    NOT NULL,
    spreadsheet_url  TEXT    NOT NULL,
    title            TEXT    NOT NULL,
    parsed_json      TEXT    NOT NULL,
    status           TEXT    NOT NULL CHECK (status IN ('pending', 'confirmed', 'cancelled')),
    created_at       TEXT    NOT NULL
);
"""


# 第 4 版：搶答活動。只新增資料表，不動既有的學習單與預覽。
# 活動與組別在建立時寫入；送出只在活動結束時以一筆交易寫入（design.md D7）。
_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS activities (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    worksheet_id     INTEGER NOT NULL REFERENCES worksheets(id),
    phase            TEXT    NOT NULL
                     CHECK (phase IN ('preparing', 'running', 'ended', 'interrupted')),
    fairness_enabled INTEGER NOT NULL,
    cooldown_seconds INTEGER NOT NULL,
    cooldown_lead    INTEGER NOT NULL,
    created_at       TEXT    NOT NULL,
    started_at       TEXT,
    ended_at         TEXT
);
CREATE TABLE IF NOT EXISTS activity_teams (
    activity_id  INTEGER NOT NULL REFERENCES activities(id),
    team_id      INTEGER NOT NULL,
    name         TEXT    NOT NULL,
    code_hash    TEXT    NOT NULL,
    code_version INTEGER NOT NULL,
    PRIMARY KEY (activity_id, team_id),
    UNIQUE (activity_id, name)
);
CREATE TABLE IF NOT EXISTS activity_submissions (
    activity_id    INTEGER NOT NULL REFERENCES activities(id),
    id             INTEGER NOT NULL,
    unit_key       TEXT    NOT NULL,
    team_id        INTEGER NOT NULL,
    rank           INTEGER NOT NULL,
    invalidated    INTEGER NOT NULL,
    received_at    TEXT    NOT NULL,
    invalidated_at TEXT,
    PRIMARY KEY (activity_id, id),
    UNIQUE (activity_id, unit_key, team_id),
    UNIQUE (activity_id, unit_key, rank),
    FOREIGN KEY (activity_id, team_id) REFERENCES activity_teams(activity_id, team_id)
);
CREATE TABLE IF NOT EXISTS activity_answers (
    activity_id   INTEGER NOT NULL,
    submission_id INTEGER NOT NULL,
    question_no   INTEGER NOT NULL,
    answer        TEXT    NOT NULL,
    PRIMARY KEY (activity_id, submission_id, question_no),
    FOREIGN KEY (activity_id, submission_id) REFERENCES activity_submissions(activity_id, id)
);
"""


class Database:
    """單一連線，以鎖序列化存取（伺服器為單一程序）。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 1:
                self._conn.executescript(_DROP_V1)
            if version < 2:
                self._conn.executescript(_SCHEMA_V2)
            if version < 3:
                self._conn.executescript(_SCHEMA_V3)
            if version < 4:
                self._conn.executescript(_SCHEMA_V4)
            if version < SCHEMA_VERSION:
                self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    def schema_version(self) -> int:
        with self.read() as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
