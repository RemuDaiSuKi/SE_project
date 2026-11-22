"""已結束活動結果的 CSV 匯出（design.md D10）。"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from .contract import OUTCOME_LABELS, ActivityResult, outcome_of

CSV_HEADER = ("題號", "組別", "答案", "搶答順位", "結果")


@dataclass(frozen=True)
class CsvOutput:
    content: bytes
    record_count: int


def build_csv(result: ActivityResult) -> CsvOutput:
    names = {g.group_id: g.name for g in result.groups}
    rows: list[tuple[int, int, str, str, str]] = []
    record_count = 0
    for unit in result.units:
        for record in unit.records:
            record_count += 1
            label = OUTCOME_LABELS[outcome_of(unit, record)]
            for no in unit.question_nos:
                rows.append((no, record.rank, names[record.group_id], record.answers[no], label))
    rows.sort(key=lambda row: (row[0], row[1]))

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for no, rank, name, answer, label in rows:
        writer.writerow((no, name, answer, rank, label))
    return CsvOutput(buffer.getvalue().encode("utf-8-sig"), record_count)
