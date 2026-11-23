"""Sheets API 的 spreadsheets.get 回應 → 格子資料（design.md D2）。

API 的座標從 0 起算、合併範圍的 end 不含尾端；格子資料一律從 1 起算、含頭含尾。
值為 0 的欄位在 API 的 JSON 中可能被省略，因此一律以 0 為預設。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..worksheet.grid import Pos, SheetGrid, SpreadsheetGrid

def _value(cell: Mapping[str, Any]) -> str | None:
    """儲存格的顯示值（formattedValue）；沒有顯示內容時為 None。

    與 SpecKit 組一致：公式以計算後的顯示結果判斷，例如 `=""` 視為空白。
    """
    text = cell.get("formattedValue")
    if text is None or text == "":
        return None
    return str(text)


def _sheet(sheet: Mapping[str, Any]) -> SheetGrid:
    props = sheet.get("properties") or {}
    values: dict[Pos, object] = {}
    max_row = 0
    for block in sheet.get("data") or []:
        row0 = int(block.get("startRow", 0))
        col0 = int(block.get("startColumn", 0))
        for i, row in enumerate(block.get("rowData") or []):
            cells = row.get("values") or []
            if cells:
                max_row = max(max_row, row0 + i + 1)
            for j, cell in enumerate(cells):
                value = _value(cell or {})
                if value is not None:
                    values[(row0 + i + 1, col0 + j + 1)] = value
    merges = tuple(
        (int(m.get("startRowIndex", 0)) + 1, int(m.get("startColumnIndex", 0)) + 1,
         int(m.get("endRowIndex", 0)), int(m.get("endColumnIndex", 0)))
        for m in sheet.get("merges") or []
    )
    max_row = max([max_row] + [m[2] for m in merges])
    return SheetGrid(
        sheet_id=int(props.get("sheetId", 0)),
        title=str(props.get("title", "")),
        values=values,
        merges=merges,
        max_row=max_row,
    )


def grid_from_sheets_api(data: Mapping[str, Any]) -> SpreadsheetGrid:
    sheets = [
        _sheet(sheet)
        for sheet in sorted(data.get("sheets") or [],
                            key=lambda s: int((s.get("properties") or {}).get("index", 0)))
        if (sheet.get("properties") or {}).get("sheetType", "GRID") == "GRID"
    ]
    return SpreadsheetGrid(
        spreadsheet_id=str(data.get("spreadsheetId", "")),
        title=str((data.get("properties") or {}).get("title", "")),
        sheets=tuple(sheets),
    )
