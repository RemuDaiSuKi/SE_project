from __future__ import annotations

from app.google.convert import grid_from_sheets_api

from .conftest import FIXTURES
from .fake_google import FakeSheetsGateway


def test_coordinates_and_merges_converted_to_one_based_inclusive():
    data = {
        "spreadsheetId": "abc",
        "properties": {"title": "標題"},
        "sheets": [{
            "properties": {"sheetId": 7, "title": "工作表1", "index": 0, "sheetType": "GRID"},
            "merges": [{"sheetId": 7, "startRowIndex": 4, "endRowIndex": 6,
                        "startColumnIndex": 1, "endColumnIndex": 2},
                       {"endRowIndex": 1, "endColumnIndex": 3}],   # 起點為 0 被省略
            "data": [{"startRow": 2, "startColumn": 1, "rowData": [
                {"values": [{"formattedValue": "題號"}]},
            ]}],
        }],
    }
    grid = grid_from_sheets_api(data)
    sheet = grid.sheets[0]
    assert (grid.spreadsheet_id, grid.title) == ("abc", "標題")
    assert (sheet.sheet_id, sheet.title) == (7, "工作表1")
    assert sheet.values == {(3, 2): "題號"}
    assert sheet.merges == ((5, 2, 6, 2), (1, 1, 1, 3))
    assert sheet.max_row == 6


def test_values_are_display_text():
    # 與 SpecKit 組一致：讀取顯示值；公式以計算結果判斷，`=""` 的顯示值是空字串
    row = {"values": [
        {"formattedValue": "文字"},
        {"formattedValue": "3"},
        {"formattedValue": "TRUE"},
        {"formattedValue": ""},                      # 例如公式 =""
        {"formattedValue": "#REF!"},
        {"userEnteredFormat": {"backgroundColor": {}}},   # 只有格式
        {"formattedValue": "　"},                     # 只有空白字元：保留，由 parser 判斷
        {},
    ]}
    data = {"sheets": [{"properties": {"title": "s"}, "data": [{"rowData": [row]}]}]}
    values = grid_from_sheets_api(data).sheets[0].values
    assert values == {(1, 1): "文字", (1, 2): "3", (1, 3): "TRUE", (1, 5): "#REF!", (1, 7): "　"}
    assert grid_from_sheets_api(data).sheets[0].sheet_id == 0  # sheetId 0 被省略


def test_chart_sheets_skipped_and_order_by_index():
    data = {"sheets": [
        {"properties": {"sheetId": 2, "title": "第二", "index": 2, "sheetType": "GRID"}},
        {"properties": {"sheetId": 9, "title": "圖表", "index": 1, "sheetType": "OBJECT"}},
        {"properties": {"sheetId": 1, "title": "第一", "hidden": True}},
    ]}
    assert [s.title for s in grid_from_sheets_api(data).sheets] == ["第一", "第二"]


def test_real_samples_round_trip_through_api_format():
    gateway = FakeSheetsGateway()
    spreadsheet_id = gateway.add(FIXTURES / "sample_b.xlsx")
    sheet = gateway.fetch(spreadsheet_id).sheets[0]
    assert (5, 2, 6, 2) in sheet.merges and (8, 2, 9, 2) in sheet.merges
    assert sheet.values[(5, 7)] == "（1）"
    assert (5, 8) not in sheet.values  # H5 為空白填空格
