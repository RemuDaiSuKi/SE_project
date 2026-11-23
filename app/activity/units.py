"""由已確認學習單的解析結果推導搶答單位與標示（與 SpecKit 組一致）。"""

from __future__ import annotations

from dataclasses import dataclass

from ..worksheet.model import ParsedWorksheet, Question


@dataclass(frozen=True)
class BuzzUnit:
    key: str                       # 單題 "Q<no>"；題組 "G<group_no>"
    question_nos: tuple[int, ...]
    display: str


def _source(questions: list[Question]) -> str:
    """括號內的學習單原始題號與子題標籤；兩者都沒有時省略括號。不含工作表名。"""
    label = questions[0].source_no
    subs = "".join(q.sub_label or "" for q in questions)
    if not label and not subs:
        return ""
    return f"（學習單第 {label or '?'} 題{subs}）"


def build_units(parsed: ParsedWorksheet) -> list[BuzzUnit]:
    """題組 → G<題組號>，其餘題目 → Q<系統題號>；依單位內最小的系統題號排序。"""
    by_no = {q.no: q for q in parsed.questions}
    units: list[BuzzUnit] = []
    for group in parsed.groups:
        questions = [by_no[n] for n in group.question_nos]
        nos = "、".join(map(str, group.question_nos))
        units.append(BuzzUnit(f"G{group.group_no}", tuple(group.question_nos),
                              f"題組 {group.group_no}：第 {nos} 題{_source(questions)}"))
    for q in parsed.questions:
        if q.group_no is None:
            units.append(BuzzUnit(f"Q{q.no}", (q.no,), f"第 {q.no} 題{_source([q])}"))
    return sorted(units, key=lambda u: u.question_nos[0])
