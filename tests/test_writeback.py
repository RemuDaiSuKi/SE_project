from __future__ import annotations

import io
import zipfile
from urllib.parse import unquote

import openpyxl
import pytest
from lxml import etree

from app.worksheet.writeback import rebuild_zip, set_cell_texts

from .conftest import FIXTURES, login
from .results_helpers import group, rec, result, single, units_for_sample_a, units_for_sample_b

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
SHEET = "xl/worksheets/sheet1.xml"

# ---------------------------------------------------------------- XML unit


def _sheet(rows_xml: str) -> bytes:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{NS}" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
            ' xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"'
            f' mc:Ignorable="x14ac"><sheetData>{rows_xml}</sheetData></worksheet>').encode()


def _cell(xml: bytes, ref: str) -> etree._Element:
    root = etree.fromstring(xml)
    return root.find(f".//{{{NS}}}c[@r='{ref}']")


def _text(xml: bytes, ref: str) -> str:
    return _cell(xml, ref).find(f"{{{NS}}}is/{{{NS}}}t").text


def test_self_closing_cell_keeps_style():
    out = set_cell_texts(_sheet('<row r="5"><c r="G5" s="15"/><c r="H5" s="16"/></row>'), {"H5": "答"})
    cell = _cell(out, "H5")
    assert cell.get("s") == "16" and cell.get("t") == "inlineStr"
    assert _text(out, "H5") == "答"
    assert _cell(out, "G5").get("t") is None


def test_declaration_and_prefixes_preserved():
    out = set_cell_texts(_sheet('<row r="5"><c r="H5"/></row>'), {"H5": "x"})
    assert out.startswith(b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    assert b'mc:Ignorable="x14ac"' in out and b"ns0:" not in out


def test_missing_cell_inserted_in_column_order():
    out = set_cell_texts(_sheet('<row r="5" spans="2:3"><c r="B5"/><c r="J5"/></row>'), {"E5": "x"})
    refs = [c.get("r") for c in etree.fromstring(out).iter(f"{{{NS}}}c")]
    assert refs == ["B5", "E5", "J5"]


def test_missing_row_inserted_in_order():
    out = set_cell_texts(_sheet('<row r="3"><c r="A3"/></row><row r="9"><c r="A9"/></row>'),
                         {"C5": "x"})
    rows = [r.get("r") for r in etree.fromstring(out).iter(f"{{{NS}}}row")]
    assert rows == ["3", "5", "9"] and _text(out, "C5") == "x"


def test_row_appended_at_end_and_spans_extended():
    out = set_cell_texts(_sheet('<row r="2" spans="1:2"><c r="A2"/></row>'), {"F2": "a", "B7": "b"})
    row2 = etree.fromstring(out).find(f".//{{{NS}}}row[@r='2']")
    assert row2.get("spans") == "1:6"
    assert _text(out, "B7") == "b"


@pytest.mark.parametrize("answer", ["=1+1", "a<b & c", '他說"好"', "第一行\n第二行", "  前後空白  "])
def test_special_text_is_preserved(answer):
    out = set_cell_texts(_sheet('<row r="1"><c r="A1"/></row>'), {"A1": answer})
    assert _text(out, "A1") == answer
    assert _cell(out, "A1").find(f"{{{NS}}}f") is None


def test_existing_value_replaced():
    out = set_cell_texts(_sheet('<row r="1"><c r="A1" t="s"><v>3</v></c></row>'), {"A1": "新"})
    cell = _cell(out, "A1")
    assert cell.find(f"{{{NS}}}v") is None and _text(out, "A1") == "新"


def test_illegal_xml_characters_removed():
    out = set_cell_texts(_sheet('<row r="1"><c r="A1"/></row>'), {"A1": "a\x00b\x07c"})
    assert _text(out, "A1") == "abc"


def test_rebuild_zip_copies_other_entries():
    original = (FIXTURES / "sample_a.xlsx").read_bytes()
    rebuilt = rebuild_zip(original, {SHEET: b"<new/>"})
    old, new = zipfile.ZipFile(io.BytesIO(original)), zipfile.ZipFile(io.BytesIO(rebuilt))
    assert [i.filename for i in old.infolist()] == [i.filename for i in new.infolist()]
    for info in old.infolist():
        if info.filename != SHEET:
            assert new.read(info.filename) == old.read(info.filename)
            assert new.getinfo(info.filename).compress_type == info.compress_type
    assert new.read(SHEET) == b"<new/>"


# ---------------------------------------------------------------- API


def confirm(client, headers, name: str) -> int:
    data = (FIXTURES / name).read_bytes()
    preview = client.post("/api/worksheets/previews", headers=headers,
                          files={"file": (name, data, "application/octet-stream")}).json()
    return client.post(f"/api/worksheets/previews/{preview['previewId']}/confirm",
                       headers=headers).json()["id"]


def _canonical_without(xml: bytes, refs: set[str]) -> bytes:
    root = etree.fromstring(xml)
    for cell in root.iter(f"{{{NS}}}c"):
        if cell.get("r") in refs:
            cell.attrib.pop("t", None)
            for child in list(cell):
                cell.remove(child)
    return etree.tostring(root, method="c14n")


def _assert_only_fill_cells_changed(original: bytes, written: bytes, refs: set[str]) -> None:
    old, new = zipfile.ZipFile(io.BytesIO(original)), zipfile.ZipFile(io.BytesIO(written))
    assert [i.filename for i in old.infolist()] == [i.filename for i in new.infolist()]
    for info in old.infolist():
        if info.filename == SHEET:
            assert _canonical_without(old.read(SHEET), refs) == _canonical_without(new.read(SHEET), refs)
        else:
            assert old.read(info.filename) == new.read(info.filename), info.filename


def _workbook(content: bytes):
    return openpyxl.load_workbook(io.BytesIO(content)).active


def test_writeback_sample_a_all_answered(client, teacher, results, data_dir):
    ws_id = confirm(client, teacher, "sample_a.xlsx")
    answers = {no: f"第{no}題答案" for no in range(1, 7)}
    results.results[1] = result(ws_id, *[single(no, rec(1, 1 + no % 3, {no: answers[no]}))
                                         for no in range(1, 7)])
    response = client.post("/api/activities/1/writeback", headers=teacher)
    assert response.status_code == 200
    assert response.headers["x-empty-questions"] == ""
    disposition = response.headers["content-disposition"]
    assert unquote(disposition.split("filename*=UTF-8''")[1]) == "sample_a_搶答結果.xlsx"
    sheet = _workbook(response.content)
    assert [sheet[f"G{r}"].value for r in (5, 7, 9, 11, 13, 15)] == [answers[n] for n in range(1, 7)]
    assert "G5:H5" in {str(m) for m in sheet.merged_cells.ranges}
    original = (FIXTURES / "sample_a.xlsx").read_bytes()
    _assert_only_fill_cells_changed(original, response.content, {f"G{r}" for r in (5, 7, 9, 11, 13, 15)})


def test_writeback_partial_leaves_blanks(client, teacher, results):
    ws_id = confirm(client, teacher, "sample_a.xlsx")
    units = units_for_sample_a()
    units[0] = single(1, rec(1, 1, {1: "一"}))
    units[2] = single(3, rec(1, 2, {3: "三"}))
    results.results[1] = result(ws_id, *units)
    response = client.post("/api/activities/1/writeback", headers=teacher)
    assert response.headers["x-empty-questions"] == "2,4,5,6"
    sheet = _workbook(response.content)
    assert sheet["G5"].value == "一" and sheet["G7"].value is None and sheet["G9"].value == "三"


def test_writeback_group_sample_b(client, teacher, results):
    ws_id = confirm(client, teacher, "sample_b.xlsx")
    units = units_for_sample_b()
    units[0] = group(1, (1, 2), rec(1, 1, {1: "甲", 2: "乙"}))
    results.results[1] = result(ws_id, *units)
    response = client.post("/api/activities/1/writeback", headers=teacher)
    sheet = _workbook(response.content)
    assert (sheet["H5"].value, sheet["H6"].value) == ("甲", "乙")
    assert (sheet["G5"].value, sheet["G6"].value) == ("（1）", "（2）")
    assert response.headers["x-empty-questions"] == "3,4,5,6"
    original = (FIXTURES / "sample_b.xlsx").read_bytes()
    _assert_only_fill_cells_changed(original, response.content, {"H5", "H6"})


def test_writeback_uses_backfilled_answer_and_ignores_request_body(client, teacher, results):
    ws_id = confirm(client, teacher, "sample_a.xlsx")
    units = units_for_sample_a()
    units[2] = single(3, rec(1, 1, {3: "A組"}, invalidated=True), rec(2, 2, {3: "B組"}))
    results.results[1] = result(ws_id, *units)
    response = client.post("/api/activities/1/writeback", headers=teacher,
                           json={"answers": {"3": "偽造"}})
    assert _workbook(response.content)["G9"].value == "B組"


def test_writeback_text_not_formula(client, teacher, results):
    ws_id = confirm(client, teacher, "sample_a.xlsx")
    units = units_for_sample_a()
    units[0] = single(1, rec(1, 1, {1: "=1+1"}))
    units[1] = single(2, rec(1, 1, {2: "a<b & c\n第二行"}))
    results.results[1] = result(ws_id, *units)
    sheet = _workbook(client.post("/api/activities/1/writeback", headers=teacher).content)
    assert sheet["G5"].value == "=1+1" and sheet["G5"].data_type == "s"
    assert sheet["G7"].value == "a<b & c\n第二行"


def test_writeback_twice_original_unchanged(client, teacher, results, data_dir):
    ws_id = confirm(client, teacher, "sample_a.xlsx")
    results.results[1] = result(ws_id, single(1, rec(1, 1, {1: "x"})), *units_for_sample_a()[1:])
    stored = next((data_dir / "worksheets").iterdir())
    before = stored.read_bytes()
    first = client.post("/api/activities/1/writeback", headers=teacher)
    second = client.post("/api/activities/1/writeback", headers=teacher)
    assert first.status_code == second.status_code == 200
    assert stored.read_bytes() == before == (FIXTURES / "sample_a.xlsx").read_bytes()


def test_writeback_rejects_tampered_original(client, teacher, results, data_dir):
    ws_id = confirm(client, teacher, "sample_a.xlsx")
    results.results[1] = result(ws_id, *units_for_sample_a())
    stored = next((data_dir / "worksheets").iterdir())
    stored.write_bytes((FIXTURES / "sample_b.xlsx").read_bytes())
    response = client.post("/api/activities/1/writeback", headers=teacher)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["message"] == "學習單結構與匯入時不一致，無法寫回"
    messages = [d["message"] for d in error["details"]]
    assert "原始檔案內容已在匯入後被修改" in messages
    assert any("位置或題組不一致" in m for m in messages)
    assert response.headers["content-type"].startswith("application/json")


def test_writeback_uses_import_time_labels(make_client, settings, password, results):
    client = make_client()
    headers = login(client, password)
    ws_id = confirm(client, headers, "sample_a.xlsx")
    results.results[1] = result(ws_id, *units_for_sample_a())
    changed = settings.model_copy(update={"label_no": "編號", "label_question": "問題",
                                          "label_answer": "回答"})
    restarted = make_client(settings_override=changed)
    headers2 = login(restarted, password)
    assert restarted.post("/api/activities/1/writeback", headers=headers2).status_code == 200


def test_writeback_requires_ended_activity(client, teacher, results):
    assert client.post("/api/activities/9/writeback", headers=teacher).json()["error"]["message"] == "找不到活動"
    results.not_ended.add(2)
    response = client.post("/api/activities/2/writeback", headers=teacher)
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "只能對已結束的活動寫回答案"


def test_writeback_default_source_not_found(make_client, password):
    from app.main import create_app
    from fastapi.testclient import TestClient

    from .conftest import BASE_URL

    client = make_client()
    app = create_app(client.app.state.buzzer.settings)  # 未注入結果來源
    with TestClient(app, base_url=BASE_URL) as plain:
        headers = login(plain, password)
        assert plain.post("/api/activities/1/writeback", headers=headers).status_code == 404
        assert plain.get("/api/activities/1/results.csv", headers=headers).status_code == 404
    app.state.buzzer.db.close()
