"""把 openpyxl 活頁簿轉成 Sheets API spreadsheets.get 格式的 JSON（測試用）。

刻意省略值為 0 的欄位，模擬 Google 回應的 proto3 JSON 慣例。
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from openpyxl.cell.cell import MergedCell

SHEET_ID_STEP = 111  # 第一個工作表 ID 為 0（會被省略），之後為 111、222…


def _omit_zero(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v != 0}


def _cell_json(cell: Any) -> dict[str, Any]:
    if isinstance(cell, MergedCell) or cell.value is None:
        return {}
    value = cell.value
    if isinstance(value, bool):
        entered = {"boolValue": value}
    elif isinstance(value, (int, float)):
        entered = {"numberValue": value}
    elif isinstance(value, (datetime, date, time)):
        entered = {"stringValue": value.isoformat()}
    elif isinstance(value, str) and value.startswith("="):
        entered = {"formulaValue": value}
    else:
        entered = {"stringValue": str(value)}
    return {"userEnteredValue": entered}


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
