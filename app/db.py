"""SQLite 連線與 schema。"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS worksheets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    original_filename TEXT    NOT NULL,
    stored_name       TEXT    NOT NULL UNIQUE,
    file_sha256       TEXT    NOT NULL,
    label_no          TEXT    NOT NULL,
    label_question    TEXT    NOT NULL,
    label_answer      TEXT    NOT NULL,
    question_count    INTEGER NOT NULL,
    group_count       INTEGER NOT NULL,
    confirmed_at      TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS worksheet_groups (
    worksheet_id INTEGER NOT NULL REFERENCES worksheets(id) ON DELETE CASCADE,
    group_no     INTEGER NOT NULL,
    source_no    TEXT,
    sheet_name   TEXT    NOT NULL,
    range_ref    TEXT    NOT NULL,
    PRIMARY KEY (worksheet_id, group_no)
);
CREATE TABLE IF NOT EXISTS worksheet_questions (
    worksheet_id INTEGER NOT NULL REFERENCES worksheets(id) ON DELETE CASCADE,
    no           INTEGER NOT NULL,
    sheet_name   TEXT    NOT NULL,
    sheet_part   TEXT    NOT NULL,
    cell_ref     TEXT    NOT NULL,
    row          INTEGER NOT NULL,
    source_no    TEXT,
    sub_label    TEXT,
    group_no     INTEGER,
    PRIMARY KEY (worksheet_id, no)
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
            if version < 1:
                self._conn.executescript(_SCHEMA_V1)
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
