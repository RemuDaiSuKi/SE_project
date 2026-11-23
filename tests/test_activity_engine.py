"""判定引擎、代碼、搶答單位與輸錯限制的單元測試（不需要 FastAPI）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.activity import codes
from app.activity.engine import (
    ENDED,
    NO_SUBMISSION,
    NO_WINNER,
    OPEN,
    PREPARING,
    RUNNING,
    WON,
    ActivityEngine,
    ActivityInfo,
    TeamState,
)
from app.activity.errors import (
    InvalidState,
    NotEnded,
    NotFound,
    PersistFailed,
    RejectReason,
    SubmissionRejected,
    TooManyAttempts,
)
from app.activity.join_limiter import JoinLimiter
from app.activity.units import build_units
from app.results.contract import validate_result, winning_answers
from app.worksheet.model import Labels, ParsedWorksheet, Question, QuestionGroup

run = asyncio.run
LABELS = Labels("題號", "題目", "作答")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Repo:
    def __init__(self) -> None:
        self.phases: list[str] = []
        self.persisted: list | None = None
        self.invalidations: list[int] = []
        self.codes: list[tuple[int, int]] = []
        self.fail_persist = False
        self.fail_invalidation = False

    def update_phase(self, activity_id, phase, *, started_at=None):
        self.phases.append(phase)

    def persist_results(self, activity_id, submissions, ended_at):
        if self.fail_persist:
            raise OSError("disk full")
        self.persisted = [(s.id, s.unit_key, s.team_id, s.rank, s.invalidated, dict(s.answers))
                          for s in submissions]

    def update_invalidation(self, activity_id, submission_id, invalidated_at):
        if self.fail_invalidation:
            raise OSError("disk full")
        self.invalidations.append(submission_id)

    def update_team_code(self, activity_id, team_id, code_hash, code_version):
        self.codes.append((team_id, code_version))


def q(no: int, source: str | None = None, sub: str | None = None,
      group: int | None = None) -> Question:
    return Question(no=no, sheet_id=0, sheet_name="學習單", cell_ref=f"G{no + 4}", row=no + 4,
                    source_no=source, sub_label=sub, group_no=group)


def sample_b() -> ParsedWorksheet:
    questions = (q(1, "1", "（1）", 1), q(2, "1", "（2）", 1), q(3, "2", "（1）", 2),
                 q(4, "2", "（2）", 2), q(5, "3"), q(6, "4"))
    groups = (QuestionGroup(1, "1", 0, "學習單", "B5:B6", (1, 2)),
              QuestionGroup(2, "2", 0, "學習單", "B8:B9", (3, 4)))
    return ParsedWorksheet(LABELS, questions, groups)


def singles(n: int) -> ParsedWorksheet:
    return ParsedWorksheet(LABELS, tuple(q(i, str(i)) for i in range(1, n + 1)), ())


def make_engine(parsed: ParsedWorksheet | None = None, teams: int = 3, *, phase: str = RUNNING,
                fairness: bool = True, n: int = 10, k: int = 2, max_len: int = 200,
                clock: Clock | None = None, repo: Repo | None = None) -> ActivityEngine:
    info = ActivityInfo(id=1, worksheet_id=1, phase=phase, fairness_enabled=fairness,
                        cooldown_seconds=n, cooldown_lead=k,
                        created_at=datetime(2026, 11, 23, tzinfo=timezone.utc))
    used: set[str] = set()
    team_states = {}
    for i in range(1, teams + 1):
        code = codes.new_code(used)
        used.add(code)
        team_states[i] = TeamState(i, f"第{i}組", codes.code_hash(code), 1, code)
    return ActivityEngine(info, build_units(parsed or singles(6)), team_states, repo or Repo(),
                          max_len, clock=clock or Clock())


def submit(engine: ActivityEngine, team: int, key: str, answers: dict[int, str] | None = None):
    if answers is None:
        unit = next(u for u in engine.units if u.key == key)
        answers = {no: f"答{team}-{no}" for no in unit.question_nos}
    version = engine.teams[team].code_version
    return run(engine.submit(team, version, key, answers))


def rejected(engine, team, key, answers=None) -> SubmissionRejected:
    with pytest.raises(SubmissionRejected) as info:
        submit(engine, team, key, answers)
    return info.value


# ---------- 代碼 ----------

def test_code_alphabet_and_uniqueness():
    assert len(codes.ALPHABET) == 32 and "L" in codes.ALPHABET
    assert not set("01IO") & set(codes.ALPHABET)
    used: set[str] = set()
    for _ in range(200):
        code = codes.new_code(used)
        assert code not in used and codes.is_well_formed(code)
        used.add(code)


def test_code_normalize_and_format():
    assert codes.normalize(" ab2 cd　3 ") == "AB2CD3"
    assert codes.is_well_formed("AB2CD3")
    assert not codes.is_well_formed("AB2CD")       # 5 碼
    assert not codes.is_well_formed("AB2CD0")      # 0 不在字元集
    assert not codes.is_well_formed("AB2CDI")
    assert codes.code_hash("AB2CD3") != "AB2CD3" and len(codes.code_hash("AB2CD3")) == 64


# ---------- 單位與標示 ----------

def test_sample_b_units_and_display():
    units = build_units(sample_b())
    assert [(u.key, u.question_nos) for u in units] == [
        ("G1", (1, 2)), ("G2", (3, 4)), ("Q5", (5,)), ("Q6", (6,))]
    assert units[0].display == "題組 1：第 1、2 題（學習單第 1 題（1）（2））"
    assert units[2].display == "第 5 題（學習單第 3 題）"


def test_display_without_source_no():
    parsed = ParsedWorksheet(LABELS, (q(1, None, "（甲）"), q(2, None, None)), ())
    units = build_units(parsed)
    assert units[0].display == "第 1 題（學習單第 ? 題（甲））"
    assert units[1].display == "第 2 題"


def test_units_sorted_by_smallest_question_no():
    questions = (q(1, "1"), q(2, "2", None, 1), q(3, "2", None, 1), q(4, "3"))
    parsed = ParsedWorksheet(LABELS, questions, (QuestionGroup(1, "2", 0, "學習單", "B6:B7", (2, 3)),))
    assert [u.key for u in build_units(parsed)] == ["Q1", "G1", "Q4"]


# ---------- 階段 ----------

def test_phase_only_moves_forward():
    repo = Repo()
    engine = make_engine(phase=PREPARING, repo=repo)
    with pytest.raises(InvalidState, match="只有搶答中的活動可以結束"):
        run(engine.end())
    run(engine.start())
    assert engine.phase == RUNNING and repo.phases == [RUNNING]
    with pytest.raises(InvalidState, match="只有準備中的活動可以開始搶答"):
        run(engine.start())
    run(engine.end())
    assert engine.phase == ENDED
    with pytest.raises(InvalidState, match="只有準備中的活動可以開始搶答"):
        run(engine.start())


def test_start_requires_units_and_teams():
    engine = make_engine(phase=PREPARING, teams=0)
    with pytest.raises(InvalidState, match="至少需要 1 個搶答單位與 1 個組別"):
        run(engine.start())


def test_persist_failure_keeps_running():
    repo = Repo()
    engine = make_engine(repo=repo)
    submit(engine, 1, "Q1")
    repo.fail_persist = True
    with pytest.raises(PersistFailed, match="結果保存失敗，活動仍在進行中，請再試一次"):
        run(engine.end())
    assert engine.phase == RUNNING
    submit(engine, 2, "Q2")  # 仍可送出
    repo.fail_persist = False
    events = run(engine.end())
    assert engine.phase == ENDED and len(repo.persisted) == 2
    assert [e.payload["type"] for e in events] == ["phaseChanged", "snapshot"]


# ---------- 送出 ----------

def test_first_come_first_served():
    engine = make_engine()
    first, _ = submit(engine, 1, "Q5")
    second, _ = submit(engine, 2, "Q5")
    assert first == {"unitKey": "Q5", "rank": 1, "outcome": "success", "message": "搶答成功！"}
    assert second["message"] == "未搶到，第 2 順位" and second["outcome"] == "lost"


def test_submission_check_order():
    engine = make_engine(phase=PREPARING)
    assert rejected(engine, 1, "NOPE", {}).message == "目前不在搶答時間"
    run(engine.start())
    # 代碼版本已更新
    with pytest.raises(SubmissionRejected) as info:
        run(engine.submit(1, 99, "Q1", {1: "a"}))
    assert info.value.reason is RejectReason.CODE_OUTDATED
    assert rejected(engine, 1, "NOPE", {}).message == "找不到這個搶答單位"
    assert rejected(engine, 1, "Q1", {1: "  "}).message == "第 1 題的答案不可為空白"
    submit(engine, 1, "Q1")
    assert rejected(engine, 1, "Q1").message == "本組已作答此題"


def test_cooldown_checked_before_unit():
    engine = make_engine(k=1)
    submit(engine, 1, "Q1")  # 1 − 0 = 1 ≥ 1：冷卻
    error = rejected(engine, 1, "NOPE", {})
    assert error.reason is RejectReason.COOLDOWN
    assert error.message == "本組領先其他組別，冷卻中，請在 10 秒後再送出"
    assert error.extra == {"retryAfterSeconds": 10}


def test_rejected_submission_leaves_no_record():
    engine = make_engine()
    rejected(engine, 1, "Q1", {1: ""})
    assert engine.submissions == []
    result, _ = submit(engine, 1, "Q1", {1: "  好  "})
    assert result["rank"] == 1 and engine.submissions[0].answers == {1: "好"}


def test_answer_length_boundary():
    engine = make_engine()
    assert rejected(engine, 1, "Q1", {1: "字" * 201}).message == "第 1 題的答案超過 200 字"
    assert submit(engine, 1, "Q1", {1: "字" * 200})[0]["rank"] == 1


def test_control_characters_not_checked():
    engine = make_engine()
    assert submit(engine, 1, "Q1", {1: "a\x07b\nc"})[0]["outcome"] == "success"


def test_group_must_be_complete():
    engine = make_engine(sample_b())
    assert rejected(engine, 1, "G1", {1: "甲"}).message == "題組必須一次送出全部題目的答案。缺少第 2 題"
    error = rejected(engine, 1, "G1", {1: "甲", 5: "x"})
    assert error.message == "題組必須一次送出全部題目的答案。缺少第 2 題；第 5 題不屬於這個單位"
    assert error.extra == {"missing": [2], "unexpected": [5]}
    # 只針對題組中的子題單獨送出：單位不存在
    assert rejected(engine, 1, "Q1", {1: "甲"}).reason is RejectReason.UNKNOWN_UNIT
    # 依單位內的題號順序檢查答案
    assert rejected(engine, 1, "G1", {2: "", 1: ""}).message == "第 1 題的答案不可為空白"
    result, _ = submit(engine, 1, "G1", {1: "甲", 2: "乙"})
    assert result["outcome"] == "success" and engine.wins()[1] == 1


def test_concurrent_submissions_get_distinct_ranks():
    engine = make_engine(teams=5, fairness=False)

    async def everyone():
        return await asyncio.gather(*(engine.submit(t, 1, "Q3", {3: f"答{t}"})
                                      for t in range(1, 6)))

    results = [r for r, _ in run(everyone())]
    assert sorted(r["rank"] for r in results) == [1, 2, 3, 4, 5]
    assert sum(r["outcome"] == "success" for r in results) == 1


def test_events_are_scoped():
    engine = make_engine()
    _, events = submit(engine, 1, "Q1")
    team_events = [e for e in events if e.audience == "team"]
    assert all(e.team_id == 1 for e in team_events)
    assert all("answers" not in e.payload for e in team_events)
    assert any(e.audience == "teacher" and e.payload["answers"] == {"1": "答1-1"} for e in events)


# ---------- 冷卻 ----------

def test_cooldown_after_leading_by_k():
    clock = Clock()
    engine = make_engine(clock=clock)
    _, events = submit(engine, 1, "Q1")
    assert engine.cooldown_remaining(1) == 0 and not [e for e in events if e.payload["type"] == "cooldown"]
    _, events = submit(engine, 1, "Q2")  # 2 − 0 = 2
    assert engine.cooldown_remaining(1) == 10
    assert {e.audience for e in events if e.payload["type"] == "cooldown"} == {"team", "teacher"}
    clock.advance(3.5)
    assert rejected(engine, 1, "Q3").message == "本組領先其他組別，冷卻中，請在 7 秒後再送出"
    assert submit(engine, 2, "Q3")[0]["rank"] == 1
    clock.advance(6.5)
    assert engine.cooldown_remaining(1) == 0
    assert submit(engine, 1, "Q3")[0]["rank"] == 2


def test_cooldown_min_includes_self():
    engine = make_engine(singles(8))
    submit(engine, 1, "Q1")
    submit(engine, 2, "Q2")           # A=1、B=1、C=0
    submit(engine, 1, "Q3")           # A=2：2 − 0 = 2
    assert engine.cooldown_remaining(1) == 10
    engine2 = make_engine(singles(8), clock=Clock())
    submit(engine2, 1, "Q1")
    submit(engine2, 2, "Q2")
    submit(engine2, 3, "Q3")
    submit(engine2, 2, "Q4")          # B=2、A=1、C=1：1，不冷卻
    submit(engine2, 1, "Q5")
    submit(engine2, 1, "Q6")          # A=3、B=2、C=1：2，冷卻
    assert engine2.cooldown_remaining(1) == 10 and engine2.cooldown_remaining(2) == 0


def test_cooldown_never_for_single_team_or_disabled():
    engine = make_engine(teams=1)
    for key in ("Q1", "Q2", "Q3", "Q4"):
        submit(engine, 1, key)
    assert engine.cooldown_remaining(1) == 0
    engine = make_engine(fairness=False)
    for key in ("Q1", "Q2", "Q3", "Q4"):
        submit(engine, 1, key)
    assert engine.cooldown_remaining(1) == 0


def test_group_counts_once_and_override():
    engine = make_engine(sample_b(), k=3, n=5)
    submit(engine, 1, "G1")
    submit(engine, 1, "G2")
    assert engine.wins()[1] == 2 and engine.cooldown_remaining(1) == 0
    submit(engine, 1, "Q5")
    assert engine.cooldown_remaining(1) == 5


def test_lost_submission_does_not_trigger_cooldown():
    engine = make_engine(k=1)
    submit(engine, 2, "Q1")
    engine.cooldowns.clear()
    submit(engine, 1, "Q1")  # 未搶到
    assert engine.cooldown_remaining(1) == 0


def test_end_clears_cooldowns():
    engine = make_engine(k=1)
    submit(engine, 1, "Q1")
    run(engine.end())
    assert engine.cooldowns == {}


def test_cooldown_hidden_from_other_teams():
    engine = make_engine(k=1)
    submit(engine, 1, "Q1")
    assert engine.view_for_team(1)["cooldownRemaining"] == 10
    view_b = engine.view_for_team(2)
    assert view_b["cooldownRemaining"] == 0 and "teams" not in view_b
    assert engine.view_for_teacher()["teams"][0]["cooldownRemaining"] == 10


# ---------- 判定無效 ----------

def test_invalidate_promotes_next_without_cooldown():
    engine = make_engine(k=1)
    submit(engine, 1, "Q5")
    engine.cooldowns.clear()
    submit(engine, 2, "Q5")
    result, events = run(engine.invalidate("Q5"))
    assert result == {"unitKey": "Q5", "invalidatedTeamId": 1, "promotedTeamId": 2,
                      "unitStatus": WON}
    assert engine.wins() == {1: 0, 2: 1, 3: 0}
    assert engine.cooldown_remaining(2) == 0  # 遞補不觸發冷卻
    team_msgs = {(e.team_id, e.payload["message"]) for e in events if e.audience == "team"}
    assert team_msgs == {(1, "第 5 題（學習單第 5 題）的答案已被老師判定無效"),
                         (2, "第 5 題（學習單第 5 題）遞補為搶答成功")}
    assert all("answers" not in e.payload for e in events)


def test_invalidate_reopens_unit_while_running():
    engine = make_engine(fairness=False)
    submit(engine, 1, "Q5")
    result, _ = run(engine.invalidate("Q5"))
    assert result["promotedTeamId"] is None and result["unitStatus"] == OPEN
    assert rejected(engine, 1, "Q5").message == "本組已作答此題"
    reopened, _ = submit(engine, 3, "Q5")
    assert reopened["rank"] == 2 and reopened["outcome"] == "success"


def test_reopened_success_checks_cooldown():
    engine = make_engine(k=1)
    submit(engine, 1, "Q5")
    engine.cooldowns.clear()
    run(engine.invalidate("Q5"))
    submit(engine, 3, "Q5")  # 即時送出成功：C=1、最少 0
    assert engine.cooldown_remaining(3) == 10


def test_invalidate_twice():
    engine = make_engine(fairness=False)
    for team in (1, 2, 3):
        submit(engine, team, "Q5")
    run(engine.invalidate("Q5"))
    result, _ = run(engine.invalidate("Q5"))
    assert result["invalidatedTeamId"] == 2 and result["promotedTeamId"] == 3
    outcomes = [(s["teamId"], s["outcome"]) for s in engine.view_for_teacher()["units"][4]["submissions"]]
    assert outcomes == [(1, "invalid"), (2, "invalid"), (3, "success")]


def test_invalidate_rejections():
    engine = make_engine(phase=PREPARING)
    with pytest.raises(InvalidState, match="只有搶答中或已結束的活動可以判定無效"):
        run(engine.invalidate("Q1"))
    run(engine.start())
    with pytest.raises(NotFound, match="找不到這個搶答單位"):
        run(engine.invalidate("Q99"))
    with pytest.raises(InvalidState, match="這個搶答單位目前沒有成功者，無法判定無效"):
        run(engine.invalidate("Q1"))


def test_invalidating_trigger_releases_cooldown():
    engine = make_engine()
    submit(engine, 1, "Q1")
    submit(engine, 1, "Q2")
    assert engine.cooldown_remaining(1) == 10
    _, events = run(engine.invalidate("Q2"))
    assert engine.cooldown_remaining(1) == 0
    released = [e for e in events if e.payload["type"] == "cooldown"]
    assert {(e.audience, e.payload["active"]) for e in released} == {("team", False), ("teacher", False)}
    assert submit(engine, 1, "Q3")[0]["outcome"] == "success"


def test_invalidating_other_success_keeps_cooldown():
    engine = make_engine()
    submit(engine, 1, "Q1")
    submit(engine, 1, "Q2")
    run(engine.invalidate("Q1"))  # 不是觸發冷卻的那筆
    assert engine.cooldown_remaining(1) == 10


def test_invalidate_after_end_writes_first():
    repo = Repo()
    engine = make_engine(repo=repo)
    submit(engine, 1, "Q5")
    run(engine.end())
    repo.fail_invalidation = True
    with pytest.raises(OSError):
        run(engine.invalidate("Q5"))
    assert not engine.submissions[0].invalidated  # 寫入失敗時記憶體不變
    repo.fail_invalidation = False
    result, _ = run(engine.invalidate("Q5"))
    assert result["unitStatus"] == NO_WINNER and repo.invalidations == [1]
    assert winning_answers(engine.to_result()) == {}


# ---------- 代碼重新產生 ----------

def test_regenerate_code_keeps_records():
    repo = Repo()
    engine = make_engine(repo=repo, k=1)
    old = engine.teams[1].code
    submit(engine, 1, "Q1")
    code, events = run(engine.regenerate_code(1))
    assert code != old and engine.teams[1].code_version == 2 and repo.codes == [(1, 2)]
    assert engine.find_team_by_code(old) is None
    assert engine.find_team_by_code(code).id == 1
    assert events[0].audience == "revoke" and events[0].team_id == 1
    assert len(engine.submissions) == 1 and engine.cooldown_remaining(1) == 10
    with pytest.raises(SubmissionRejected) as info:
        run(engine.submit(1, 1, "Q2", {2: "x"}))
    assert info.value.reason is RejectReason.CODE_OUTDATED


def test_regenerate_code_only_while_live():
    engine = make_engine()
    run(engine.end())
    with pytest.raises(InvalidState, match="活動已結束或已中斷，不能重新產生代碼"):
        run(engine.regenerate_code(1))
    engine = make_engine()
    with pytest.raises(NotFound, match="找不到這個組別"):
        run(engine.regenerate_code(9))


# ---------- 檢視 ----------

def test_views_isolate_teams_until_end():
    engine = make_engine(sample_b())
    submit(engine, 2, "Q5")
    submit(engine, 1, "Q5")
    view = engine.view_for_team(1)
    assert view["mySubmissions"] == [{"unitKey": "Q5", "rank": 2, "outcome": "lost",
                                      "answers": {"5": "答1-5"}}]
    assert view["results"] is None
    assert all(set(u) == {"key", "display", "questionNos"} for u in view["units"])
    assert "答2-5" not in repr(view)
    with pytest.raises(NotEnded, match="活動尚未結束，結束後才能檢視結果"):
        engine.results_view(include_all=True)

    teacher = engine.view_for_teacher()
    assert [u["status"] for u in teacher["units"]] == [NO_SUBMISSION, NO_SUBMISSION, WON, NO_SUBMISSION]
    assert all(t["code"] for t in teacher["teams"])

    run(engine.end())
    view = engine.view_for_team(1)
    q5 = next(u for u in view["results"]["units"] if u["key"] == "Q5")
    assert q5["winner"] == {"teamId": 2, "teamName": "第2組", "answers": {"5": "答2-5"}}
    assert "submissions" not in q5
    assert view["results"]["units"][0]["status"] == NO_WINNER
    assert {t["id"]: t["wins"] for t in view["results"]["teams"]} == {1: 0, 2: 1, 3: 0}
    assert all(t["code"] is None for t in engine.view_for_teacher()["teams"])
    full = engine.results_view(include_all=True)
    assert len(next(u for u in full["units"] if u["key"] == "Q5")["submissions"]) == 2


def test_to_result_satisfies_contract():
    engine = make_engine(sample_b(), fairness=False)
    submit(engine, 1, "G1", {1: "甲", 2: "乙"})
    submit(engine, 2, "G1", {1: "丙", 2: "丁"})
    submit(engine, 3, "Q6")
    run(engine.invalidate("G1"))
    run(engine.end())
    result = engine.to_result()
    validate_result(result)
    assert winning_answers(result) == {1: "丙", 2: "丁", 6: "答3-6"}


# ---------- 輸錯限制 ----------

def test_join_limiter_window_lock():
    clock = Clock()
    limiter = JoinLimiter(5, 60, 60, clock)
    for _ in range(5):
        limiter.check_allowed("w1")
        limiter.record_failure("w1")
    with pytest.raises(TooManyAttempts) as info:
        limiter.check_allowed("w1")
    assert info.value.message == "代碼輸入錯誤次數過多，請於 60 秒後再試"
    limiter.check_allowed("w2")  # 其他視窗不受影響
    clock.advance(59.5)
    with pytest.raises(TooManyAttempts) as info:
        limiter.check_allowed("w1")
    assert info.value.remaining_seconds == 1
    clock.advance(0.5)
    limiter.check_allowed("w1")
    # 鎖定時計數已歸零：再錯 4 次不會鎖定
    for _ in range(4):
        limiter.record_failure("w1")
    limiter.check_allowed("w1")


def test_join_limiter_success_resets():
    limiter = JoinLimiter(5, 60, 60, Clock())
    for _ in range(4):
        limiter.record_failure("w1")
    limiter.record_success("w1")
    for _ in range(4):
        limiter.record_failure("w1")
    limiter.check_allowed("w1")


def test_join_limiter_global_limit():
    clock = Clock()
    limiter = JoinLimiter(5, 60, 60, clock)
    for i in range(60):
        limiter.record_failure(f"w{i}")
        clock.advance(0.5)
    with pytest.raises(TooManyAttempts) as info:
        limiter.check_allowed("fresh")
    assert info.value.remaining_seconds == 30  # 最早的失敗在 30 秒前
    clock.advance(30)
    limiter.check_allowed("fresh")
