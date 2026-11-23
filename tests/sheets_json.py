"""把 openpyxl 活頁簿轉成 Sheets API spreadsheets.get 格式的 JSON（測試用）。

儲存格只輸出顯示值（formattedValue），和伺服器實際向 Google 要求的欄位相同。

刻意省略值為 0 的欄位，模擬 Google 回應的 proto3 JSON 慣例。
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from openpyxl.cell.cell import MergedCell

SHEET_ID_STEP = 111  # 第一個工作表 ID 為 0（會被省略），之後為 111、222…


def _omit_zero(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v != 0}


def formatted(value: Any) -> str:
    """模擬 Google 試算表的顯示值（formattedValue）。

    整數值的數字顯示成「3」而不是「3.0」；公式 `=""` 顯示為空字串。
    openpyxl 無法計算其他公式，測試中不使用。
    """
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if value == '=""':
        return ""
    return str(value)


def _cell_json(cell: Any) -> dict[str, Any]:
    if isinstance(cell, MergedCell) or cell.value is None:
        return {}
    text = formatted(cell.value)
    return {"formattedValue": text} if text != "" else {}


def workbook_to_sheets_json(workbook: Any, spreadsheet_id: str = "TestSpreadsheetId0000001",
                            title: str = "測試學習單") -> dict[str, Any]:
    sheets = []
    for index, ws in enumerate(workbook.worksheets):
        sheet_id = index * SHEET_ID_STEP
        rows = []
        for r in range(1, ws.max_row + 1):
            values = [_cell_json(ws.cell(r, c)) for c in range(1, ws.max_column + 1)]
            while values and not values[-1]:
                values.pop()
            rows.append({"values": values} if values else {})
        merges = [
            _omit_zero({"sheetId": sheet_id, "startRowIndex": m.min_row - 1, "endRowIndex": m.max_row,
                        "startColumnIndex": m.min_col - 1, "endColumnIndex": m.max_col})
            for m in ws.merged_cells.ranges
        ]
        props = _omit_zero({"sheetId": sheet_id, "title": ws.title, "index": index})
        props["sheetType"] = "GRID"
        if ws.sheet_state != "visible":
            props["hidden"] = True
        sheet: dict[str, Any] = {"properties": props, "data": [{"rowData": rows}]}
        if merges:
            sheet["merges"] = merges
        sheets.append(sheet)
    return {"spreadsheetId": spreadsheet_id, "properties": {"title": title}, "sheets": sheets}
