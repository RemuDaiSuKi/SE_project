"""把成功答案直接寫回原 Google 試算表（design.md D7）。"""

from __future__ import annotations

from dataclasses import dataclass

from ..google.gateway import CellWrite, SheetsGateway
from ..results.contract import ActivityResult, winning_answers
from .grid import Pos, SpreadsheetGrid, split_ref
from .model import ImportRejected, Labels, ParsedWorksheet
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


def _placement(q) -> tuple:  # noqa: ANN001
    """結構比對的欄位：工作表 ID、工作表名稱、填空格與所屬題組（與 SpecKit 組一致）。"""
    return (q.sheet_id, q.sheet_name, q.cell_ref, q.group_no)


def verify_structure(grid: SpreadsheetGrid, expected: ParsedWorksheet, labels: Labels,
                     max_questions: int | None = None) -> None:
    """以目前的表頭設定重新解析試算表，比對每題的填空格位置。

    填空格是否有內容不算結構差異。比對包含工作表名稱，所以匯入後改了分頁名稱也會被拒絕。
    遇到第一個差異就停止，只回報一項。
    """
    fills: dict[int, set[Pos]] = {}
    for q in expected.questions:
        fills.setdefault(q.sheet_id, set()).add(split_ref(q.cell_ref))
    blanked = SpreadsheetGrid(
        grid.spreadsheet_id, grid.title,
        tuple(s.without(fills.get(s.sheet_id, set())) for s in grid.sheets),
    )
    try:
        current = parse_grid(blanked, labels, max_questions)
    except ImportRejected as exc:
        raise StructureMismatch(["目前的學習單" + exc.issues[0].message]) from None

    if current.question_count != expected.question_count:
        raise StructureMismatch([f"題數由 {expected.question_count} 題變成 "
                                 f"{current.question_count} 題"])
    for old, new in zip(expected.questions, current.questions):
        if _placement(old) != _placement(new):
            raise StructureMismatch([f"第 {old.no} 題原本在 {old.location}，現在在 {new.location}"])


def write_back(result: ActivityResult, worksheet: StoredWorksheet,
               gateway: SheetsGateway, labels: Labels,
               max_questions: int | None = None) -> WritebackReport:
    grid = gateway.fetch(worksheet.spreadsheet_id)
    verify_structure(grid, worksheet.parsed, labels, max_questions)

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
        writes.append(CellWrite(question.sheet_name, question.cell_ref, answers[question.no]))
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
