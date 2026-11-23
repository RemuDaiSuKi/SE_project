"""活動的保存、重啟與結果來源（不需要 FastAPI）。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.activity import codes
from app.activity.engine import ENDED, INTERRUPTED, PREPARING, RUNNING
from app.activity.errors import ActivityInProgress, ActivityInterrupted, InvalidInput, NotFound
from app.activity.registry import ActivityRegistry
from app.activity.results import SqliteResultSource
from app.db import Database
from app.results.contract import outcome_of, success_counts, validate_result, winning_answers
from app.worksheet.store import Preview, WorksheetStore

from .test_activity_engine import sample_b, singles

run = asyncio.run
SETTINGS = SimpleNamespace(max_teams=20, team_name_max=20, max_answer_length=200,
                           fairness_enabled=True, cooldown_seconds=10, cooldown_lead=2)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "buzzer.db")
    yield database
    database.close()


def add_worksheet(db, parsed=None) -> int:
    preview = Preview("p", "S" * 20, "https://example/x", "測試", parsed or sample_b())
    return WorksheetStore(db).save(preview).id


def registry(db, **overrides) -> ActivityRegistry:
    settings = SimpleNamespace(**{**vars(SETTINGS), **overrides})
    return ActivityRegistry(db, WorksheetStore(db), settings, clock=Clock())


def test_create_validates_teams(db):
    reg = registry(db)
    ws = add_worksheet(db)
    with pytest.raises(InvalidInput, match="組名不可重複：甲"):
        reg.create(ws, ["甲", "乙", " 甲 "], None, None, None)
    with pytest.raises(InvalidInput, match="第 2 組的組名不可為空白"):
        reg.create(ws, ["甲", "  "], None, None, None)
    with pytest.raises(InvalidInput, match="組數必須是 1–20 組"):
        reg.create(ws, [f"{i}" for i in range(21)], None, None, None)
    with pytest.raises(InvalidInput, match="第 1 組的組名超過 20 字"):
        reg.create(ws, ["字" * 21], None, None, None)
    with pytest.raises(NotFound, match="找不到學習單"):
        reg.create(999, ["甲"], None, None, None)
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0


def test_create_stores_hash_only_and_single_live(db):
    reg = registry(db)
    ws = add_worksheet(db)
    engine = reg.create(ws, ["A 組", "B 組", "C 組"], None, 5, None)
    assert engine.phase == PREPARING and [u.key for u in engine.units] == ["G1", "G2", "Q5", "Q6"]
    assert engine.info.cooldown_seconds == 5 and engine.info.cooldown_lead == 2
    plain = [t.code for t in engine.teams.values()]
    assert len(set(plain)) == 3
    with db.read() as conn:
        rows = conn.execute("SELECT name, code_hash FROM activity_teams").fetchall()
        dump = "\n".join(conn.iterdump())
    assert [r["code_hash"] for r in rows] == [codes.code_hash(c) for c in plain]
    assert not any(c in dump for c in plain)
    with pytest.raises(ActivityInProgress):
        reg.create(ws, ["甲"], None, None, None)
    run(engine.start())
    with pytest.raises(ActivityInProgress):
        reg.create(ws, ["甲"], None, None, None)
    run(engine.end())
    assert reg.create(ws, ["甲"], False, None, None).info.fairness_enabled is False


def test_find_team_only_in_live_activity(db):
    reg = registry(db)
    engine = reg.create(add_worksheet(db), ["A", "B"], None, None, None)
    code = engine.teams[2].code
    assert reg.find_team_by_code(code)[1].id == 2
    run(engine.start())
    run(engine.end())
    assert reg.find_team_by_code(code) is None


def test_restart_marks_unfinished_interrupted(db):
    reg = registry(db)
    ws = add_worksheet(db)
    ended = reg.create(ws, ["A"], None, None, None)
    run(ended.start())
    run(ended.end())
    running = reg.create(ws, ["A"], None, None, None)
    run(running.start())

    reg2 = registry(db)
    assert reg2.startup() == 1
    assert reg2.phase_of(running.id) == INTERRUPTED
    with pytest.raises(ActivityInterrupted, match="活動已中斷（伺服器曾重新啟動），請老師重新建立活動"):
        reg2.get(running.id)
    assert reg2.current is None
    assert [a["phase"] for a in reg2.list()] == [INTERRUPTED, ENDED]
    assert reg2.create(ws, ["新"], None, None, None).phase == PREPARING
    with pytest.raises(NotFound, match="找不到活動"):
        reg2.get(999)


def test_end_persists_and_reload_after_restart(db):
    reg = registry(db)
    ws = add_worksheet(db)
    engine = reg.create(ws, ["A", "B", "C"], False, None, None)
    run(engine.start())
    run(engine.submit(1, 1, "G1", {1: "甲", 2: "乙"}))
    run(engine.submit(2, 1, "G1", {1: "丙", 2: "丁"}))
    run(engine.submit(3, 1, "Q5", {5: "戊"}))
    with db.read() as conn:  # 搶答中的送出只在記憶體
        assert conn.execute("SELECT COUNT(*) FROM activity_submissions").fetchone()[0] == 0
    run(engine.end())
    before = engine.results_view(include_all=True)

    reg2 = registry(db)
    reg2.startup()
    loaded = reg2.get(engine.id)
    assert loaded is not engine and loaded.phase == ENDED
    assert loaded.results_view(include_all=True) == before
    assert all(t["code"] is None for t in loaded.view_for_teacher()["teams"])

    # 重啟後判定無效：先寫入資料庫，重啟後仍然反映遞補
    run(loaded.invalidate("G1"))
    reg3 = registry(db)
    result = SqliteResultSource(reg3.repo, WorksheetStore(db)).lookup(engine.id).result
    validate_result(result)
    assert winning_answers(result) == {1: "丙", 2: "丁", 5: "戊"}
    assert success_counts(result) == {1: 0, 2: 1, 3: 1}
    g1 = result.units[0]
    assert [outcome_of(g1, r) for r in g1.records] == ["invalid", "success"]


def test_persist_failure_keeps_running(db):
    reg = registry(db)
    engine = reg.create(add_worksheet(db, singles(3)), ["A"], None, None, None)
    run(engine.start())
    run(engine.submit(1, 1, "Q1", {1: "a"}))
    original = engine.repo.persist_results

    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    engine.repo.persist_results = broken  # type: ignore[method-assign]
    with pytest.raises(Exception, match="結果保存失敗"):
        run(engine.end())
    assert engine.phase == RUNNING and reg.phase_of(engine.id) == RUNNING
    engine.repo.persist_results = original  # type: ignore[method-assign]
    run(engine.end())
    assert reg.phase_of(engine.id) == ENDED


def test_result_source_states(db):
    reg = registry(db)
    source = SqliteResultSource(reg.repo, WorksheetStore(db))
    assert source.lookup(1).status == "not_found"
    engine = reg.create(add_worksheet(db, singles(3)), ["A", "B"], None, None, None)
    assert source.lookup(engine.id).status == "not_ended"
    run(engine.start())
    assert source.lookup(engine.id).status == "not_ended"
    run(engine.submit(2, 1, "Q2", {2: "二"}))
    run(engine.end())
    lookup = source.lookup(engine.id)
    assert lookup.status == "ended"
    validate_result(lookup.result)
    assert [u.unit_id for u in lookup.result.units] == ["Q1", "Q2", "Q3"]
    assert winning_answers(lookup.result) == {2: "二"}
    assert [g.name for g in lookup.result.groups] == ["A", "B"]


def test_regenerated_code_persisted(db):
    reg = registry(db)
    engine = reg.create(add_worksheet(db), ["A", "B"], None, None, None)
    code, _ = run(engine.regenerate_code(2))
    with db.read() as conn:
        row = conn.execute("SELECT code_hash, code_version FROM activity_teams WHERE team_id = 2").fetchone()
    assert (row["code_hash"], row["code_version"]) == (codes.code_hash(code), 2)
