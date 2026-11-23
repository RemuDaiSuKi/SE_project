"""測試用的假 Google 存取層（不連網）。"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import openpyxl

from app.google.convert import grid_from_sheets_api
from app.google.errors import SheetsError
from app.google.gateway import CellWrite
from app.worksheet.grid import SpreadsheetGrid, split_ref

from .sheets_json import workbook_to_sheets_json


def sheet_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid=0"


class FakeSheetsGateway:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.writes: list[tuple[str, list[CellWrite]]] = []
        self.fetch_error: SheetsError | None = None
        self.write_error: SheetsError | None = None
        self.fetch_count = 0

    # ------------------------------------------------------------ setup

    def add(self, source: Any, spreadsheet_id: str | None = None, title: str = "測試學習單") -> str:
        """加入一份試算表；source 可以是 openpyxl 活頁簿或 .xlsx 路徑。"""
        workbook = openpyxl.load_workbook(source) if isinstance(source, (str, Path)) else source
        spreadsheet_id = spreadsheet_id or f"FakeSpreadsheet{len(self.docs) + 1:02d}abcdefghij"
        self.docs[spreadsheet_id] = workbook_to_sheets_json(workbook, spreadsheet_id, title)
        return spreadsheet_id

    def _sheet(self, spreadsheet_id: str, title: str) -> dict[str, Any]:
        for sheet in self.docs[spreadsheet_id]["sheets"]:
            if sheet["properties"]["title"] == title:
                return sheet
        raise KeyError(title)

    def set_value(self, spreadsheet_id: str, sheet_title: str, ref: str, text: str | None) -> None:
        sheet = self._sheet(spreadsheet_id, sheet_title)
        row, col = split_ref(ref)
        rows = sheet["data"][0]["rowData"]
        while len(rows) < row:
            rows.append({})
        values = rows[row - 1].setdefault("values", [])
        while len(values) < col:
            values.append({})
        # 以 RAW 寫入的文字原樣顯示
        values[col - 1] = {} if not text else {"formattedValue": text}

    def rename_sheet(self, spreadsheet_id: str, old: str, new: str) -> None:
        self._sheet(spreadsheet_id, old)["properties"]["title"] = new

    def delete_sheet(self, spreadsheet_id: str, title: str) -> None:
        sheets = self.docs[spreadsheet_id]["sheets"]
        sheets.remove(self._sheet(spreadsheet_id, title))

    def insert_row(self, spreadsheet_id: str, sheet_title: str, before_row: int) -> None:
        sheet = self._sheet(spreadsheet_id, sheet_title)
        sheet["data"][0]["rowData"].insert(before_row - 1, {})
        for merge in sheet.get("merges", []):
            if merge.get("startRowIndex", 0) >= before_row - 1:
                merge["startRowIndex"] = merge.get("startRowIndex", 0) + 1
                merge["endRowIndex"] = merge.get("endRowIndex", 0) + 1

    def grid(self, spreadsheet_id: str) -> SpreadsheetGrid:
        return grid_from_sheets_api(copy.deepcopy(self.docs[spreadsheet_id]))

    def value(self, spreadsheet_id: str, sheet_title: str, ref: str) -> object:
        sheet = next(s for s in self.grid(spreadsheet_id).sheets if s.title == sheet_title)
        return sheet.values.get(split_ref(ref))

    # ------------------------------------------------------------ SheetsGateway

    def fetch(self, spreadsheet_id: str) -> SpreadsheetGrid:
        self.fetch_count += 1
        if self.fetch_error is not None:
            raise self.fetch_error
        if spreadsheet_id not in self.docs:
            raise SheetsError("not_found", 404)
        return self.grid(spreadsheet_id)

    def write_cells(self, spreadsheet_id: str, writes: Sequence[CellWrite]) -> None:
        if self.write_error is not None:
            raise self.write_error
        self.writes.append((spreadsheet_id, list(writes)))
        for write in writes:
            self.set_value(spreadsheet_id, write.sheet_title, write.cell_ref, write.text)
