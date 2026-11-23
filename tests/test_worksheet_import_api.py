from __future__ import annotations

import pytest

from app.google.errors import SheetsError
from app.worksheet.model import Labels, ParsedWorksheet
from app.db import Database
from app.worksheet.store import PreviewStore

from . import builders
from .conftest import FIXTURES, import_worksheet, login
from .fake_google import sheet_url

# ---------------------------------------------------------------- preview store unit


def _parsed() -> ParsedWorksheet:
    return ParsedWorksheet(Labels("題號", "題目", "作答"), (), ())


def _add(store: PreviewStore, name: str = "s"):
    return store.add(name, sheet_url(name), "標題", _parsed())


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "buzzer.db")
    yield PreviewStore(db)
    db.close()


def test_preview_confirmed_once(store):
    preview = _add(store)
    saved = []
    assert store.confirm(preview.preview_id, saved.append) is None  # save 的回傳值
    assert [p.preview_id for p in saved] == [preview.preview_id]
    assert saved[0].parsed == preview.parsed
    assert store.confirm(preview.preview_id, saved.append) is None and len(saved) == 1
    assert store.cancel(preview.preview_id) is False


def test_preview_cancelled_once(store):
    preview = _add(store)
    assert store.cancel(preview.preview_id) is True
    assert store.cancel(preview.preview_id) is False
    assert store.confirm(preview.preview_id, lambda p: p) is None


def test_preview_no_expiry_or_cap(store):
    # 與 SpecKit 組一致：預覽沒有有效期限，也沒有份數上限
    previews = [_add(store, str(i)) for i in range(20)]
    assert all(store.confirm(p.preview_id, lambda x: x) is not None for p in previews)


def test_preview_survives_reopen(tmp_path):
    db = Database(tmp_path / "buzzer.db")
    parsed = ParsedWorksheet(Labels("題號", "題目", "作答"), (), ())
    preview = PreviewStore(db).add("s", sheet_url("s"), "標題", parsed)
    db.close()
    db = Database(tmp_path / "buzzer.db")
    restored = PreviewStore(db).confirm(preview.preview_id, lambda p: p)
    assert restored == preview
    db.close()


# ---------------------------------------------------------------- API


def preview(client, headers, url: str):
    return client.post("/api/worksheets/previews", headers=headers, json={"url": url})


def test_preview_sample_a(client, teacher, gateway):
    sid = gateway.add(FIXTURES / "sample_a.xlsx", title="軟工期末專案_單題_範例")
    response = preview(client, teacher, sheet_url(sid))
    assert response.status_code == 201
    body = response.json()
    assert body["spreadsheetTitle"] == "軟工期末專案_單題_範例"
    assert body["spreadsheetUrl"] == f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    assert body["questionCount"] == 6 and body["groupCount"] == 0
    assert [q["location"] for q in body["questions"]] == [
        f"學習單!G{r}" for r in (5, 7, 9, 11, 13, 15)]
    assert body["questions"][0] == {"no": 1, "sourceNo": "1", "subLabel": None, "sheet": "學習單",
                                    "cell": "G5", "location": "學習單!G5", "groupNo": None}
    assert "電腦系統" not in response.text  # 不回傳題目敘述


def test_preview_sample_b(client, teacher, gateway):
    sid = gateway.add(FIXTURES / "sample_b.xlsx")
    body = preview(client, teacher, sid).json()  # 也接受純試算表 ID
    assert body["questionCount"] == 6 and body["groupCount"] == 2
    assert [(q["no"], q["cell"], q["subLabel"], q["groupNo"]) for q in body["questions"]] == [
        (1, "H5", "（1）", 1), (2, "H6", "（2）", 1), (3, "H8", "（1）", 2), (4, "H9", "（2）", 2),
        (5, "G11", None, None), (6, "G13", None, None)]
    assert body["groups"][0] == {"groupNo": 1, "sourceNo": "1", "sheet": "學習單",
                                 "range": "B5:B6", "questionNos": [1, 2]}


def test_preview_does_not_create_worksheet(client, teacher, gateway):
    preview(client, teacher, sheet_url(gateway.add(builders.sample_a())))
    assert client.get("/api/worksheets", headers=teacher).json()["worksheets"] == []


@pytest.mark.parametrize("url", ["https://example.com/abc", "   ", "not-an-id",
                                 "https://docs.google.com/spreadsheets/d/e/2PACX-abcdefghijklmnopqrstuvwxyz/pubhtml"])
def test_invalid_url(client, teacher, gateway, url):
    response = preview(client, teacher, url)
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "請輸入有效的 Google 試算表網址"
    assert gateway.fetch_count == 0


@pytest.mark.parametrize("kind,status,message", [
    ("not_authorized", 409, "尚未完成 Google 授權，請先執行 python -m app google-login"),
    ("auth_expired", 409, "Google 授權已失效，請重新執行 python -m app google-login"),
    ("forbidden", 403, "目前登入的 Google 帳號沒有這份試算表的編輯權限，"
                       "請改用有權限的帳號重新登入，或請擁有者把試算表共用給這個帳號（編輯者）"),
    ("unavailable", 502, "目前無法連線到 Google 試算表，請稍後再試"),
])
def test_google_errors_on_import(client, teacher, gateway, kind, status, message):
    sid = gateway.add(builders.sample_a())
    gateway.fetch_error = SheetsError(kind)
    response = preview(client, teacher, sheet_url(sid))
    assert response.status_code == status
    assert response.json()["error"] == {"code": f"GOOGLE_{kind.upper()}", "message": message}
    assert client.get("/api/worksheets", headers=teacher).json()["worksheets"] == []


def test_forbidden_on_import_names_account(client, teacher, gateway):
    sid = gateway.add(builders.sample_a())
    gateway.fetch_error = SheetsError("forbidden", 403, "teacher@example.com")
    message = preview(client, teacher, sid).json()["error"]["message"]
    assert message.startswith("目前登入的 Google 帳號（teacher@example.com）沒有這份試算表的編輯權限")


def test_unknown_spreadsheet(client, teacher):
    response = preview(client, teacher, "UnknownSpreadsheetId123456789")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "找不到試算表，請確認網址是否正確"


def test_confirm_creates_worksheet(client, teacher, gateway):
    sid = gateway.add(FIXTURES / "sample_b.xlsx", title="題組範例")
    body = preview(client, teacher, sheet_url(sid)).json()
    response = client.post(f"/api/worksheets/previews/{body['previewId']}/confirm", headers=teacher)
    assert response.status_code == 201
    created = response.json()
    assert (created["title"], created["questionCount"], created["groupCount"]) == ("題組範例", 6, 2)
    assert created["spreadsheetUrl"] == body["spreadsheetUrl"]
    listing = client.get("/api/worksheets", headers=teacher).json()["worksheets"]
    assert [w["id"] for w in listing] == [created["id"]]
    detail = client.get(f"/api/worksheets/{created['id']}", headers=teacher).json()
    assert detail["questions"] == body["questions"] and detail["groups"] == body["groups"]


def test_double_confirm_rejected(client, teacher, gateway):
    body = preview(client, teacher, gateway.add(builders.sample_a())).json()
    url = f"/api/worksheets/previews/{body['previewId']}/confirm"
    assert client.post(url, headers=teacher).status_code == 201
    again = client.post(url, headers=teacher)
    assert again.status_code == 409
    assert again.json()["error"]["message"] == "這份預覽已確認或已取消，請重新讀取試算表"
    assert len(client.get("/api/worksheets", headers=teacher).json()["worksheets"]) == 1


def test_cancel_then_confirm_rejected(client, teacher, gateway):
    sid = gateway.add(builders.sample_a())
    pid = preview(client, teacher, sid).json()["previewId"]
    assert client.delete(f"/api/worksheets/previews/{pid}", headers=teacher).status_code == 200
    assert client.post(f"/api/worksheets/previews/{pid}/confirm", headers=teacher).status_code == 409
    assert client.delete(f"/api/worksheets/previews/{pid}", headers=teacher).status_code == 409
    assert client.get("/api/worksheets", headers=teacher).json()["worksheets"] == []
    assert preview(client, teacher, gateway.add(builders.sample_b())).status_code == 201


def test_preview_does_not_expire(client, teacher, password, gateway, clock):
    pid = preview(client, teacher, gateway.add(builders.sample_a())).json()["previewId"]
    clock.advance(24 * 3600)
    headers = login(client, password)  # 老師 Token 只有 8 小時，重新登入後再確認
    response = client.post(f"/api/worksheets/previews/{pid}/confirm", headers=headers)
    assert response.status_code == 201


def test_preview_confirmable_after_restart(make_client, password, gateway):
    first = make_client()
    headers = login(first, password)
    kept = preview(first, headers, gateway.add(builders.sample_a())).json()
    first.post(f"/api/worksheets/previews/{kept['previewId']}/confirm", headers=headers)
    pending = preview(first, headers, gateway.add(builders.sample_b())).json()

    second = make_client()
    headers2 = login(second, password)
    # 與 SpecKit 組一致：未確認的預覽存在資料庫，重啟後仍可確認
    response = second.post(f"/api/worksheets/previews/{pending['previewId']}/confirm",
                           headers=headers2)
    assert response.status_code == 201
    listing = second.get("/api/worksheets", headers=headers2).json()["worksheets"]
    assert [w["questionCount"] for w in listing] == [6, 6]
    detail = second.get(f"/api/worksheets/{listing[0]['id']}", headers=headers2).json()
    assert detail["questions"] == kept["questions"]
    assert second.get(f"/api/worksheets/{listing[1]['id']}",
                      headers=headers2).json()["questions"] == pending["questions"]


def test_same_spreadsheet_can_be_imported_twice(client, teacher, gateway):
    sid = gateway.add(builders.sample_a())
    for _ in range(2):
        pid = preview(client, teacher, sid).json()["previewId"]
        client.post(f"/api/worksheets/previews/{pid}/confirm", headers=teacher)
    ids = [w["id"] for w in client.get("/api/worksheets", headers=teacher).json()["worksheets"]]
    assert len(ids) == 2 and ids[0] != ids[1]


def test_rejected_import_returns_details(client, teacher, gateway):
    response = preview(client, teacher, gateway.add(builders.multiple_errors()))
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "IMPORT_INVALID"
    assert error["message"] == "學習單有 2 處問題，未匯入"
    assert error["details"][0] == {"message": "工作表「學習單」第 7 列：作答欄沒有空白填空格",
                                   "sheet": "學習單", "location": "第 7 列"}
    assert client.get("/api/worksheets", headers=teacher).json()["worksheets"] == []


def test_blank_spreadsheet(client, teacher, gateway):
    response = preview(client, teacher, gateway.add(builders.blank_workbook()))
    assert response.json()["error"]["message"] == "找不到同時包含『題號』『題目』『作答』的表頭列"


def test_question_limit_from_settings(make_client, settings, password, gateway):
    client = make_client(settings_override=settings.model_copy(update={"max_questions": 10}))
    headers = login(client, password)
    response = preview(client, headers, gateway.add(builders.many_questions(11)))
    assert response.json()["error"]["message"] == "題目數 11 超過上限 10"


def test_labels_from_settings(make_client, settings, password, gateway):
    custom = settings.model_copy(update={"label_no": "編號", "label_question": "問題",
                                         "label_answer": "回答"})
    client = make_client(settings_override=custom)
    headers = login(client, password)
    response = preview(client, headers, gateway.add(builders.custom_labels()))
    assert response.status_code == 201 and response.json()["questionCount"] == 6


def test_import_helper_and_unknown_worksheet(client, teacher, gateway):
    ws_id = import_worksheet(client, teacher, gateway, builders.sample_a())
    assert client.get(f"/api/worksheets/{ws_id}", headers=teacher).status_code == 200
    response = client.get("/api/worksheets/999", headers=teacher)
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "找不到學習單"


def test_preview_requires_teacher(client, gateway):
    response = preview(client, {}, gateway.add(builders.sample_a()))
    assert response.status_code == 403
    assert gateway.fetch_count == 0


# ---------------------------------------------------------------- Google 授權狀態


def test_google_status_endpoint_removed(client, teacher):
    # 與 SpecKit 組一致：老師頁面不顯示 Google 授權狀態（未授權時伺服器不會啟動）
    assert client.get("/api/google/status", headers=teacher).status_code == 404
