"""活動最終結果（ActivityResult）契約，design.md D8。

由搶答活動（第二個 change）產生，由寫回與 CSV 匯出讀取。
每個搶答單位的成功送出一律推導為「順位最小且未被判定無效」的那筆，
全系統的判定都必須使用本模組的函式。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

Outcome = Literal["success", "lost", "invalid"]

OUTCOME_LABELS: dict[str, str] = {"success": "成功", "lost": "未搶到", "invalid": "無效"}
NO_WINNER_LABEL = "無人搶答"


@dataclass(frozen=True)
class ResultGroup:
    group_id: int
    name: str


@dataclass(frozen=True)
class ResultRecord:
    rank: int
    group_id: int
    answers: Mapping[int, str]  # 系統題號 → 答案
    invalidated: bool = False


@dataclass(frozen=True)
class ResultUnit:
    unit_id: str                     # 單題 "Q<no>"；題組 "G<group_no>"
    question_nos: tuple[int, ...]
    records: tuple[ResultRecord, ...]


@dataclass(frozen=True)
class ActivityResult:
    activity_id: int
    worksheet_id: int
    ended_at: datetime
    groups: tuple[ResultGroup, ...]
    units: tuple[ResultUnit, ...]


class ContractViolation(ValueError):
    """結果資料不符合契約，代表程式錯誤。"""


def winner_of(unit: ResultUnit) -> ResultRecord | None:
    valid = [r for r in unit.records if not r.invalidated]
    return min(valid, key=lambda r: r.rank) if valid else None


def outcome_of(unit: ResultUnit, record: ResultRecord) -> Outcome:
    if record.invalidated:
        return "invalid"
    winner = winner_of(unit)
    return "success" if winner is not None and winner.rank == record.rank else "lost"


def success_counts(result: ActivityResult) -> dict[int, int]:
    """各組成功數，以搶答單位計（題組算 1）。"""
    counts = {g.group_id: 0 for g in result.groups}
    for unit in result.units:
        winner = winner_of(unit)
        if winner is not None:
            counts[winner.group_id] = counts.get(winner.group_id, 0) + 1
    return counts


def winning_answers(result: ActivityResult) -> dict[int, str]:
    """系統題號 → 成功答案；沒有成功送出的題目不在其中。"""
    answers: dict[int, str] = {}
    for unit in result.units:
        winner = winner_of(unit)
        if winner is not None:
            for no in unit.question_nos:
                answers[no] = winner.answers[no]
    return answers


def validate_result(result: ActivityResult) -> None:
    group_ids = {g.group_id for g in result.groups}
    if len(group_ids) != len(result.groups):
        raise ContractViolation("duplicate group id")
    seen_units: set[str] = set()
    seen_questions: set[int] = set()
    for unit in result.units:
        if unit.unit_id in seen_units:
            raise ContractViolation(f"duplicate unit {unit.unit_id}")
        seen_units.add(unit.unit_id)
        if not unit.question_nos or seen_questions.intersection(unit.question_nos):
            raise ContractViolation(f"bad question numbers in {unit.unit_id}")
        seen_questions.update(unit.question_nos)
        ranks = sorted(r.rank for r in unit.records)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ContractViolation(f"ranks not contiguous in {unit.unit_id}")
        for record in unit.records:
            if record.group_id not in group_ids:
                raise ContractViolation(f"unknown group in {unit.unit_id}")
            if set(record.answers) != set(unit.question_nos):
                raise ContractViolation(f"answers do not match questions in {unit.unit_id}")


@dataclass(frozen=True)
class FinalResultLookup:
    status: Literal["not_found", "not_ended", "ended"]
    result: ActivityResult | None = None


class FinalResultSource(Protocol):
    def lookup(self, activity_id: int) -> FinalResultLookup: ...


class NoActivitiesSource:
    """搶答活動尚未實作前的預設來源：任何活動都不存在。"""

    def lookup(self, activity_id: int) -> FinalResultLookup:
        return FinalResultLookup("not_found")
