"""與資料來源無關的試算表格子資料（design.md D1）。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

Pos = tuple[int, int]                       # (列, 欄)，皆從 1 起算
MergeRange = tuple[int, int, int, int]      # (r0, c0, r1, c1)，含頭含尾


@dataclass(frozen=True)
class SheetGrid:
    sheet_id: int
    title: str
    values: Mapping[Pos, object]            # 只含有輸入值的儲存格
    merges: tuple[MergeRange, ...]
    max_row: int

    def without(self, positions: set[Pos]) -> "SheetGrid":
        """回傳把指定儲存格清空後的副本。"""
        values = {pos: v for pos, v in self.values.items() if pos not in positions}
        return SheetGrid(self.sheet_id, self.title, values, self.merges, self.max_row)


@dataclass(frozen=True)
class SpreadsheetGrid:
    spreadsheet_id: str
    title: str
    sheets: tuple[SheetGrid, ...]           # 依分頁順序，只含一般工作表

    def sheet(self, sheet_id: int) -> SheetGrid | None:
        return next((s for s in self.sheets if s.sheet_id == sheet_id), None)


def column_letter(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def cell_ref(pos: Pos) -> str:
    return f"{column_letter(pos[1])}{pos[0]}"


def split_ref(ref: str) -> Pos:
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    digits = "".join(ch for ch in ref if ch.isdigit())
    if not letters or not digits or letters + digits != ref.upper():
        raise ValueError(f"invalid cell reference: {ref!r}")
    column = 0
    for ch in letters:
        column = column * 26 + (ord(ch) - ord("A") + 1)
    return int(digits), column
