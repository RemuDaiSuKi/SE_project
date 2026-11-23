from __future__ import annotations

import sqlite3

from app.db import SCHEMA_VERSION, Database


def _columns(db: Database, table: str) -> set[str]:
    with db.read() as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_fresh_data_dir_creates_v3_schema(tmp_path):
    db = Database(tmp_path / "new" / "buzzer.db")
    with db.read() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert {"worksheets", "worksheet_questions", "worksheet_groups", "worksheet_previews"} <= tables
    assert db.schema_version() == SCHEMA_VERSION == 3
    assert {"spreadsheet_id", "spreadsheet_url", "title"} <= _columns(db, "worksheets")
    assert "sheet_id" in _columns(db, "worksheet_questions")
    assert journal.lower() == "wal" and foreign_keys == 1
    db.close()


def test_upgrade_from_v1_drops_old_worksheets(tmp_path):
    path = tmp_path / "buzzer.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE worksheets (id INTEGER PRIMARY KEY, original_filename TEXT, stored_name TEXT,
                                 file_sha256 TEXT);
        CREATE TABLE worksheet_questions (worksheet_id INTEGER, no INTEGER, sheet_part TEXT);
        CREATE TABLE worksheet_groups (worksheet_id INTEGER, group_no INTEGER);
        INSERT INTO worksheets VALUES (1, 'a.xlsx', 'x.xlsx', 'abc');
        PRAGMA user_version=1;
    """)
    conn.close()
    db = Database(path)
    assert db.schema_version() == 3
    assert "original_filename" not in _columns(db, "worksheets")
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == 0
    db.close()


def test_upgrade_from_v2_keeps_worksheets_and_adds_previews(tmp_path):
    path = tmp_path / "buzzer.db"
    db = Database(path)
    with db.transaction() as conn:
        conn.execute("DROP TABLE worksheet_previews")
        conn.execute(
            "INSERT INTO worksheets (spreadsheet_id, spreadsheet_url, title, label_no,"
            " label_question, label_answer, question_count, group_count, confirmed_at)"
            " VALUES ('s','u','t','a','b','c',1,0,'now')")
    with db.read() as conn:
        conn.execute("PRAGMA user_version=2")
    db.close()
    db = Database(path)
    assert db.schema_version() == 3
    assert "status" in _columns(db, "worksheet_previews")
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == 1
    db.close()


def test_reopen_is_idempotent(tmp_path):
    path = tmp_path / "buzzer.db"
    Database(path).close()
    db = Database(path)
    assert db.schema_version() == SCHEMA_VERSION
    db.close()


def test_transaction_rolls_back(tmp_path):
    db = Database(tmp_path / "buzzer.db")
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO worksheets (spreadsheet_id, spreadsheet_url, title, label_no,"
                " label_question, label_answer, question_count, group_count, confirmed_at)"
                " VALUES ('s','u','t','a','b','c',1,0,'now')")
            raise RuntimeError("fail")
    except RuntimeError:
        pass
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == 0
    db.close()
