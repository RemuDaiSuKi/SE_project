"""測試用的 ActivityResult 建構工具。"""

from __future__ import annotations

from datetime import datetime, timezone

from app.results.contract import ActivityResult, ResultGroup, ResultRecord, ResultUnit

GROUPS = (ResultGroup(1, "第一組"), ResultGroup(2, "第二組"), ResultGroup(3, "第三組"))


def rec(rank: int, group_id: int, answers: dict[int, str], invalidated: bool = False) -> ResultRecord:
    return ResultRecord(rank=rank, group_id=group_id, answers=answers, invalidated=invalidated)


def single(no: int, *records: ResultRecord) -> ResultUnit:
    return ResultUnit(f"Q{no}", (no,), tuple(records))


def group(group_no: int, nos: tuple[int, ...], *records: ResultRecord) -> ResultUnit:
    return ResultUnit(f"G{group_no}", nos, tuple(records))


def result(worksheet_id: int, *units: ResultUnit, activity_id: int = 1,
           groups: tuple[ResultGroup, ...] = GROUPS) -> ActivityResult:
    return ActivityResult(activity_id=activity_id, worksheet_id=worksheet_id,
                          ended_at=datetime(2026, 11, 22, tzinfo=timezone.utc),
                          groups=groups, units=units)


def units_for_sample_a() -> list[ResultUnit]:
    return [single(no) for no in range(1, 7)]


def units_for_sample_b() -> list[ResultUnit]:
    return [group(1, (1, 2)), group(2, (3, 4)), single(5), single(6)]
