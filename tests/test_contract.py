from __future__ import annotations

import pytest

from app.results.contract import (
    ContractViolation,
    NoActivitiesSource,
    outcome_of,
    success_counts,
    validate_result,
    winner_of,
    winning_answers,
)

from .results_helpers import group, rec, result, single


def test_first_valid_record_wins():
    unit = single(1, rec(1, 1, {1: "a"}), rec(2, 2, {1: "b"}))
    assert winner_of(unit).group_id == 1
    assert [outcome_of(unit, r) for r in unit.records] == ["success", "lost"]


def test_backfill_after_invalidation():
    unit = single(1, rec(1, 1, {1: "a"}, invalidated=True), rec(2, 2, {1: "b"}), rec(3, 3, {1: "c"}))
    assert winner_of(unit).group_id == 2
    assert [outcome_of(unit, r) for r in unit.records] == ["invalid", "success", "lost"]


def test_consecutive_invalidation():
    unit = single(1, rec(1, 1, {1: "a"}, True), rec(2, 2, {1: "b"}, True), rec(3, 3, {1: "c"}))
    assert winner_of(unit).rank == 3


def test_reopened_unit_new_submission_wins():
    # 搶答中判定無效且無人遞補 → 重新開放 → 之後的新送出拿到第 2 順位並成功
    unit = single(1, rec(1, 1, {1: "a"}, True), rec(2, 3, {1: "c"}))
    assert outcome_of(unit, unit.records[1]) == "success"


def test_all_invalid_means_no_winner():
    unit = single(1, rec(1, 1, {1: "a"}, True))
    assert winner_of(unit) is None
    assert outcome_of(unit, unit.records[0]) == "invalid"
    assert winner_of(single(2)) is None


def test_group_counts_as_one_success_and_answers_expand():
    res = result(1, group(1, (1, 2), rec(1, 2, {1: "甲", 2: "乙"})), single(3, rec(1, 2, {3: "丙"})),
                 single(4))
    assert success_counts(res) == {1: 0, 2: 2, 3: 0}
    assert winning_answers(res) == {1: "甲", 2: "乙", 3: "丙"}


def test_valid_result_passes_validation():
    validate_result(result(1, group(1, (1, 2), rec(1, 1, {1: "a", 2: "b"}), rec(2, 2, {1: "c", 2: "d"}))))


@pytest.mark.parametrize("bad", [
    result(1, single(1, rec(1, 1, {1: "a"}), rec(3, 2, {1: "b"}))),           # 順位不連續
    result(1, single(1, rec(1, 1, {1: "a"}), rec(1, 2, {1: "b"}))),           # 順位重複
    result(1, single(1, rec(1, 9, {1: "a"}))),                                # 不存在的組別
    result(1, group(1, (1, 2), rec(1, 1, {1: "a"}))),                         # 缺少子題答案
    result(1, single(1), single(1)),                                          # 單位重複
    result(1, single(1), group(1, (1, 2))),                                   # 題號重複
])
def test_contract_violations(bad):
    with pytest.raises(ContractViolation):
        validate_result(bad)


def test_default_source_has_no_activities():
    assert NoActivitiesSource().lookup(1).status == "not_found"
