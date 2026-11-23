from __future__ import annotations

import copy

import pytest

from app.google.convert import grid_from_sheets_api
from app.google.errors import SheetsError
from app.worksheet.grid import split_ref
from app.worksheet.writeback import (
    StructureMismatch,
    WritebackReport,
    verify_structure,
    writeback_message,
)

from . import builders
from .conftest import FIXTURES, import_worksheet, login
from .results_helpers import group, rec, result, single, units_for_sample_a, units_for_sample_b

SHEET = "學習單"
FILLS_A = ["G5", "G7", "G9", "G11", "G13", "G15"]


def _import(client, teacher, gateway, name: str) -> tuple[int, str]:
    ws_id = import_worksheet(client, teacher, gateway, FIXTURES / name)
    spreadsheet_id = list(gateway.docs)[-1]
    return ws_id, spreadsheet_id


def _writeback(client, headers, activity_id: int = 1):
    return client.post(f"/api/activities/{activity_id}/writeback", headers=headers)


# ---------------------------------------------------------------- message


def test_message_all_written():
    assert writeback_message(WritebackReport((1, 2, 3, 4, 5, 6), (), ())) == "已寫回全部 6 題答案。"


def test_message_mixed():
    report = WritebackReport((1, 4, 6), (2, 5), (3,))
    assert writeback_message(report) == ("已寫回 3 題答案。以下題目沒有成功答案，保持空白：第 2、5 題。"
                                         "以下填空格已有內容，未覆蓋：第 3 題。")


# ---------------------------------------------------------------- writing


def test_sample_a_all_answered(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    before = copy.deepcopy(gateway.docs[sid])
    answers = {no: f"第{no}題答案" for no in range(1, 7)}
    results.results[1] = result(ws_id, *[single(no, rec(1, 1 + no % 3, {no: answers[no]}))
                                         for no in range(1, 7)])
    response = _writeback(client, teacher)
    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "已寫回全部 6 題答案。"
    assert body["written"] == [1, 2, 3, 4, 5, 6] and body["empty"] == [] and body["skippedFilled"] == []
    assert body["spreadsheetUrl"] == f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    assert [gateway.value(sid, SHEET, ref) for ref in FILLS_A] == [answers[n] for n in range(1, 7)]
    # 單一批次寫入
    assert len(gateway.writes) == 1 and len(gateway.writes[0][1]) == 6
    # 寫回前後比對：只有填空格的值不同，合併範圍與其他儲存格都相同
    old_sheet = grid_from_sheets_api(before).sheets[0]
    new_sheet = gateway.grid(sid).sheets[0]
    fills = {split_ref(ref) for ref in FILLS_A}
    assert new_sheet.merges == old_sheet.merges
    assert {p: v for p, v in new_sheet.values.items() if p not in fills} == dict(old_sheet.values)
    assert set(new_sheet.values) - set(old_sheet.values) == fills


def test_partial_leaves_blanks(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    units = units_for_sample_a()
    units[0] = single(1, rec(1, 1, {1: "一"}))
    units[2] = single(3, rec(1, 2, {3: "三"}))
    results.results[1] = result(ws_id, *units)
    body = _writeback(client, teacher).json()
    assert body["empty"] == [2, 4, 5, 6]
    assert body["message"] == "已寫回 2 題答案。以下題目沒有成功答案，保持空白：第 2、4、5、6 題。"
    assert gateway.value(sid, SHEET, "G5") == "一" and gateway.value(sid, SHEET, "G7") is None
    assert gateway.value(sid, SHEET, "G9") == "三"


def test_group_sample_b(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_b.xlsx")
    units = units_for_sample_b()
    units[0] = group(1, (1, 2), rec(1, 1, {1: "甲", 2: "乙"}))
    results.results[1] = result(ws_id, *units)
    body = _writeback(client, teacher).json()
    assert body["written"] == [1, 2] and body["empty"] == [3, 4, 5, 6]
    assert (gateway.value(sid, SHEET, "H5"), gateway.value(sid, SHEET, "H6")) == ("甲", "乙")
    assert (gateway.value(sid, SHEET, "G5"), gateway.value(sid, SHEET, "G6")) == ("（1）", "（2）")


def test_backfilled_answer_used_and_request_body_ignored(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    units = units_for_sample_a()
    units[2] = single(3, rec(1, 1, {3: "A組"}, invalidated=True), rec(2, 2, {3: "B組"}))
    results.results[1] = result(ws_id, *units)
    client.post("/api/activities/1/writeback", headers=teacher, json={"answers": {"3": "偽造"}})
    assert gateway.value(sid, SHEET, "G9") == "B組"


def test_text_kept_as_is(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    units = units_for_sample_a()
    units[0] = single(1, rec(1, 1, {1: "=1+1"}))
    units[1] = single(2, rec(1, 1, {2: "a<b & c\n第二行"}))
    results.results[1] = result(ws_id, *units)
    _writeback(client, teacher)
    writes = {w.cell_ref: w.text for w in gateway.writes[0][1]}
    assert writes == {"G5": "=1+1", "G7": "a<b & c\n第二行"}


def test_second_writeback_skips_filled_cells(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    results.results[1] = result(ws_id, *[single(n, rec(1, 1, {n: f"答{n}"})) for n in range(1, 7)])
    _writeback(client, teacher)
    body = _writeback(client, teacher).json()
    assert body["written"] == [] and body["skippedFilled"] == [1, 2, 3, 4, 5, 6]
    assert body["message"] == "已寫回 0 題答案。以下填空格已有內容，未覆蓋：第 1、2、3、4、5、6 題。"
    assert len(gateway.writes) == 1  # 沒有東西要寫時不呼叫 API


def test_invalidation_after_writeback_keeps_old_answer(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    units = units_for_sample_a()
    units[2] = single(3, rec(1, 1, {3: "A組"}), rec(2, 2, {3: "B組"}))
    results.results[1] = result(ws_id, *units)
    _writeback(client, teacher)
    units[2] = single(3, rec(1, 1, {3: "A組"}, invalidated=True), rec(2, 2, {3: "B組"}))
    results.results[1] = result(ws_id, *units)
    body = _writeback(client, teacher).json()
    assert body["skippedFilled"] == [3]
    assert gateway.value(sid, SHEET, "G9") == "A組"
    # 老師手動清除後再寫回，才寫入遞補答案
    gateway.set_value(sid, SHEET, "G9", None)
    assert _writeback(client, teacher).json()["written"] == [3]
    assert gateway.value(sid, SHEET, "G9") == "B組"


def test_teacher_filled_cell_is_not_structure_change(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    gateway.set_value(sid, SHEET, "G5", "老師手寫")
    results.results[1] = result(ws_id, *[single(n, rec(1, 1, {n: f"答{n}"})) for n in range(1, 7)])
    body = _writeback(client, teacher).json()
    assert body["skippedFilled"] == [1] and body["written"] == [2, 3, 4, 5, 6]
    assert gateway.value(sid, SHEET, "G5") == "老師手寫"


def test_renamed_sheet_rejected(client, teacher, gateway, results):
    # 結構比對包含工作表名稱：匯入後改分頁名稱視為結構不一致（與 SpecKit 組一致）
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    gateway.rename_sheet(sid, SHEET, "第一週")
    details = _mismatch(client, teacher, results, ws_id)
    assert details == ["第 1 題原本在 學習單!G5，現在在 第一週!G5"]
    assert gateway.writes == []


# ---------------------------------------------------------------- structure verification


def _mismatch(client, teacher, results, ws_id):
    results.results[1] = result(ws_id, *[single(n, rec(1, 1, {n: "x"})) for n in range(1, 7)])
    response = _writeback(client, teacher)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["message"] == "學習單結構與匯入時不一致，無法寫回"
    return [d["message"] for d in error["details"]]


def test_inserted_row_rejected(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    gateway.insert_row(sid, SHEET, 9)
    details = _mismatch(client, teacher, results, ws_id)
    assert any("第 3 題" in d for d in details)
    assert gateway.writes == []


def test_changed_sub_label_not_checked(client, teacher, gateway, results):
    # 結構比對只看填空格位置與題組，子題標籤改了仍可寫回（與 SpecKit 組一致）
    ws_id, sid = _import(client, teacher, gateway, "sample_b.xlsx")
    gateway.set_value(sid, SHEET, "G6", "（乙）")
    units = units_for_sample_b()
    units[0] = group(1, (1, 2), rec(1, 1, {1: "甲", 2: "乙"}))
    results.results[1] = result(ws_id, *units)
    assert _writeback(client, teacher).status_code == 200
    assert gateway.value(sid, SHEET, "H6") == "乙"


def test_deleted_question_text_rejected(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    gateway.set_value(sid, SHEET, "C9", None)
    details = _mismatch(client, teacher, results, ws_id)
    assert details == ["題數由 6 題變成 5 題"]


def test_deleted_sheet_rejected(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    gateway.delete_sheet(sid, SHEET)
    details = _mismatch(client, teacher, results, ws_id)
    assert details == ["目前的學習單找不到同時包含『題號』『題目』『作答』的表頭列"]


def test_verify_structure_direct(client, teacher, gateway):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    stored = client.app.state.buzzer.worksheets.get(ws_id)
    labels = stored.parsed.labels
    verify_structure(gateway.grid(sid), stored.parsed, labels, 500)  # 不丟出例外
    gateway.insert_row(sid, SHEET, 5)
    with pytest.raises(StructureMismatch):
        verify_structure(gateway.grid(sid), stored.parsed, labels, 500)


def test_current_label_settings_used_for_verification(make_client, settings, password, gateway,
                                                      results):
    # 寫回前以「目前的」表頭設定重新解析（與 SpecKit 組一致）
    client = make_client()
    headers = login(client, password)
    ws_id = import_worksheet(client, headers, gateway, FIXTURES / "sample_a.xlsx")
    results.results[1] = result(ws_id, *units_for_sample_a())
    changed = settings.model_copy(update={"label_no": "編號", "label_question": "問題",
                                          "label_answer": "回答"})
    restarted = make_client(settings_override=changed)
    headers2 = login(restarted, password)
    response = _writeback(restarted, headers2)
    assert response.status_code == 409
    assert response.json()["error"]["details"] == [
        {"message": "目前的學習單找不到同時包含『編號』『問題』『回答』的表頭列"}]


# ---------------------------------------------------------------- failures


def test_requires_ended_activity(client, teacher, gateway, results):
    assert _writeback(client, teacher, 9).json()["error"]["message"] == "找不到活動"
    results.not_ended.add(2)
    response = _writeback(client, teacher, 2)
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "只能對已結束的活動寫回答案"
    assert gateway.fetch_count == 0


def test_forbidden_write_writes_nothing(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    results.results[1] = result(ws_id, *[single(n, rec(1, 1, {n: "x"})) for n in range(1, 7)])
    gateway.write_error = SheetsError("forbidden", 403)
    response = _writeback(client, teacher)
    assert response.status_code == 403
    assert "編輯權限" in response.json()["error"]["message"]
    assert all(gateway.value(sid, SHEET, ref) is None for ref in FILLS_A)


def test_retry_after_network_failure(client, teacher, gateway, results):
    ws_id, sid = _import(client, teacher, gateway, "sample_a.xlsx")
    gateway.set_value(sid, SHEET, "G5", "老師手寫")
    results.results[1] = result(ws_id, *[single(n, rec(1, 1, {n: f"答{n}"})) for n in range(1, 7)])
    gateway.write_error = SheetsError("unavailable")
    assert _writeback(client, teacher).status_code == 502
    gateway.write_error = None
    body = _writeback(client, teacher).json()
    assert body["written"] == [2, 3, 4, 5, 6] and body["skippedFilled"] == [1]
    assert gateway.value(sid, SHEET, "G5") == "老師手寫"


def test_default_source_not_found(make_client, password):
    from fastapi.testclient import TestClient

    from app.main import create_app

    from .conftest import BASE_URL
    from .fake_google import FakeSheetsGateway

    client = make_client()
    app = create_app(client.app.state.buzzer.settings, gateway=FakeSheetsGateway())  # 未注入結果來源
    with TestClient(app, base_url=BASE_URL) as plain:
        headers = login(plain, password)
        assert plain.post("/api/activities/1/writeback", headers=headers).status_code == 404
        assert plain.get("/api/activities/1/results.csv", headers=headers).status_code == 404
    app.state.buzzer.db.close()


def test_multi_sheet_writeback(client, teacher, gateway, results):
    ws_id = import_worksheet(client, teacher, gateway, builders.multi_sheet())
    sid = list(gateway.docs)[-1]
    results.results[1] = result(ws_id, *[single(n, rec(1, 1, {n: f"答{n}"})) for n in range(1, 8)])
    assert _writeback(client, teacher).json()["written"] == [1, 2, 3, 4, 5, 6, 7]
    assert gateway.value(sid, "第一節", "G5") == "答1" and gateway.value(sid, "第二節", "C5") == "答7"
