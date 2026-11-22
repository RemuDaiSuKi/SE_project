"""把成功答案直接寫回原 Google 試算表（design.md D7）。"""

from __future__ import annotations

from dataclasses import dataclass

from ..google.gateway import CellWrite, SheetsGateway
from ..results.contract import ActivityResult, winning_answers
from .grid import Pos, SpreadsheetGrid, split_ref
from .model import ImportRejected, ParsedWorksheet
from .parser import is_blank, parse_grid
from .store import StoredWorksheet

STRUCTURE_MISMATCH_MESSAGE = "學習單結構與匯入時不一致，無法寫回"


class StructureMismatch(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class WritebackReport:
    written: tuple[int, ...]
    empty: tuple[int, ...]
    skipped_filled: tuple[int, ...]


def verify_structure(grid: SpreadsheetGrid, expected: ParsedWorksheet) -> None:
    """重新讀取的試算表必須與匯入時的結構相同；填空格是否有內容不算結構差異。"""
    problems: list[str] = []
    names = {q.sheet_id: q.sheet_name for q in expected.questions}
    for sheet_id, name in names.items():
        if grid.sheet(sheet_id) is None:
            problems.append(f"找不到工作表「{name}」（可能已被刪除）")
    if problems:
        raise StructureMismatch(problems)

    fills: dict[int, set[Pos]] = {}
    for q in expected.questions:
        fills.setdefault(q.sheet_id, set()).add(split_ref(q.cell_ref))
    blanked = SpreadsheetGrid(
        grid.spreadsheet_id, grid.title,
        tuple(s.without(fills.get(s.sheet_id, set())) for s in grid.sheets),
    )
    try:
        current = parse_grid(blanked, expected.labels)
    except ImportRejected as exc:
        problems.append("重新解析學習單失敗：" + exc.summary)
        problems.extend(issue.message for issue in exc.issues if exc.total > 1)
        raise StructureMismatch(problems[:50]) from None

    if current.question_count != expected.question_count:
        problems.append(f"題數不一致（匯入時 {expected.question_count} 題，"
                        f"現在 {current.question_count} 題）")
    for old, new in zip(expected.questions, current.questions):
        if old.identity() != new.identity():
            problems.append(f"第 {old.no} 題的位置、題號、子題標籤或題組不一致"
                            f"（匯入時 {old.location}，現在 {new.location}）")
    if [g.identity() for g in expected.groups] != [g.identity() for g in current.groups]:
        problems.append("題組結構不一致")
    if problems:
        raise StructureMismatch(problems[:50])


def write_back(result: ActivityResult, worksheet: StoredWorksheet,
               gateway: SheetsGateway) -> WritebackReport:
    grid = gateway.fetch(worksheet.spreadsheet_id)
    verify_structure(grid, worksheet.parsed)

    answers = winning_answers(result)
    writes: list[CellWrite] = []
    written: list[int] = []
    empty: list[int] = []
    skipped: list[int] = []
    for question in worksheet.parsed.questions:
        if question.no not in answers:
            empty.append(question.no)
            continue
        sheet = grid.sheet(question.sheet_id)
        assert sheet is not None  # verify_structure 已確認
        if not is_blank(sheet.values.get(split_ref(question.cell_ref))):
            skipped.append(question.no)
            continue
        # 以目前的工作表名稱組成範圍，工作表改名也能寫入
        writes.append(CellWrite(sheet.title, question.cell_ref, answers[question.no]))
        written.append(question.no)
    if writes:
        gateway.write_cells(worksheet.spreadsheet_id, writes)
    return WritebackReport(tuple(written), tuple(empty), tuple(skipped))


def _numbers(nos: tuple[int, ...]) -> str:
    return "第 " + "、".join(str(n) for n in nos) + " 題"


def writeback_message(report: WritebackReport) -> str:
    if not report.empty and not report.skipped_filled:
        return f"已寫回全部 {len(report.written)} 題答案。"
    parts = [f"已寫回 {len(report.written)} 題答案。"]
    if report.empty:
        parts.append(f"以下題目沒有成功答案，保持空白：{_numbers(report.empty)}。")
    if report.skipped_filled:
        parts.append(f"以下填空格已有內容，未覆蓋：{_numbers(report.skipped_filled)}。")
    return "".join(parts)
