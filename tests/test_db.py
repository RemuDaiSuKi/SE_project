from __future__ import annotations

from app.db import SCHEMA_VERSION, Database


def test_fresh_data_dir_creates_schema(tmp_path):
    db = Database(tmp_path / "new" / "buzzer.db")
    with db.read() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert {"worksheets", "worksheet_questions", "worksheet_groups"} <= tables
    assert db.schema_version() == SCHEMA_VERSION
    assert journal.lower() == "wal" and foreign_keys == 1
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
                "INSERT INTO worksheets (original_filename, stored_name, file_sha256, label_no,"
                " label_question, label_answer, question_count, group_count, confirmed_at)"
                " VALUES ('a','b','c','d','e','f',1,0,'t')")
            raise RuntimeError("fail")
    except RuntimeError:
        pass
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == 0
    db.close()
