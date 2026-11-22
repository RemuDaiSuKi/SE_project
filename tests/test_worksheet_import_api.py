from __future__ import annotations

import hashlib

import pytest

from app.worksheet.model import Labels, ParsedWorksheet
from app.worksheet.store import PreviewStore, WorksheetStore, safe_filename

from . import builders
from .conftest import FIXTURES, FakeClock, login

# ---------------------------------------------------------------- preview store unit


def _parsed() -> ParsedWorksheet:
    return ParsedWorksheet(Labels("題號", "題目", "作答"), (), ())


def test_preview_expires_after_30_minutes():
    clock = FakeClock()
    store = PreviewStore(clock)
    preview = store.add("a.xlsx", b"x", _parsed())
    clock.advance(30 * 60 - 1)
    assert store.take(preview.preview_id) is preview
    other = store.add("b.xlsx", b"x", _parsed())
    clock.advance(30 * 60)
    assert store.take(other.preview_id) is None


def test_preview_cap_evicts_oldest():
    store = PreviewStore(FakeClock(), max_items=2)
    first = store.add("1", b"", _parsed())
    second = store.add("2", b"", _parsed())
    third = store.add("3", b"", _parsed())
    assert store.take(first.preview_id) is None
    assert store.take(second.preview_id) is second and store.take(third.preview_id) is third


def test_preview_taken_once():
    store = PreviewStore(FakeClock())
    preview = store.add("a", b"", _parsed())
    assert store.take(preview.preview_id) is preview
    assert store.take(preview.preview_id) is None


def test_safe_filename():
    assert safe_filename("C:\\fake\\path\\學習單.xlsx") == "學習單.xlsx"
    assert safe_filename("../../evil.xlsx") == "evil.xlsx"
    assert safe_filename(None) == "學習單.xlsx"


# ---------------------------------------------------------------- store


def test_store_rollback_removes_file(tmp_path, monkeypatch):
    from app.db import Database

    db = Database(tmp_path / "db.sqlite")
    store = WorksheetStore(db, tmp_path)
    preview = PreviewStore(FakeClock()).add("a.xlsx", b"data", _parsed())

    original = db.transaction

    def failing():
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "transaction", failing)
    with pytest.raises(RuntimeError):
        store.save(preview)
    monkeypatch.setattr(db, "transaction", original)
    assert list((tmp_path / "worksheets").iterdir()) == []
    assert store.list() == []
    db.close()


# ---------------------------------------------------------------- API


def upload(client, headers, data: bytes, filename: str = "學習單.xlsx"):
    return client.post("/api/worksheets/previews", headers=headers,
                       files={"file": (filename, data, "application/octet-stream")})


def sample(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_preview_sample_a(client, teacher):
    response = upload(client, teacher, sample("sample_a.xlsx"), "範例A.xlsx")
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "範例A.xlsx"
    assert body["questionCount"] == 6 and body["groupCount"] == 0
    assert [q["location"] for q in body["questions"]] == [
        f"學習單!G{r}" for r in (5, 7, 9, 11, 13, 15)]
    assert body["questions"][0] == {"no": 1, "sourceNo": "1", "subLabel": None, "sheet": "學習單",
                                    "cell": "G5", "location": "學習單!G5", "groupNo": None}
    # 不保存、不回傳題目敘述
    assert "電腦系統" not in response.text


def test_preview_sample_b(client, teacher):
    body = upload(client, teacher, sample("sample_b.xlsx")).json()
    assert body["questionCount"] == 6 and body["groupCount"] == 2
    assert [(q["no"], q["cell"], q["subLabel"], q["groupNo"]) for q in body["questions"]] == [
        (1, "H5", "（1）", 1), (2, "H6", "（2）", 1), (3, "H8", "（1）", 2), (4, "H9", "（2）", 2),
        (5, "G11", None, None), (6, "G13", None, None)]
    assert body["groups"][0] == {"groupNo": 1, "sourceNo": "1", "sheet": "學習單",
                                 "range": "B5:B6", "questionNos": [1, 2]}


def test_preview_does_not_create_worksheet(client, teacher):
    upload(client, teacher, sample("sample_a.xlsx"))
    assert client.get("/api/worksheets", headers=teacher).json()["worksheets"] == []


def test_confirm_creates_worksheet_and_keeps_original_bytes(client, teacher, data_dir):
    data = sample("sample_b.xlsx")
    preview = upload(client, teacher, data).json()
    response = client.post(f"/api/worksheets/previews/{preview['previewId']}/confirm",
                           headers=teacher)
    assert response.status_code == 201
    created = response.json()
    assert created["questionCount"] == 6 and created["groupCount"] == 2
    listing = client.get("/api/worksheets", headers=teacher).json()["worksheets"]
    assert [w["id"] for w in listing] == [created["id"]]
    detail = client.get(f"/api/worksheets/{created['id']}", headers=teacher).json()
    assert detail["questions"] == preview["questions"] and detail["groups"] == preview["groups"]
    stored = list((data_dir / "worksheets").iterdir())
    assert len(stored) == 1
    assert hashlib.sha256(stored[0].read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()


def test_double_confirm_rejected(client, teacher):
    preview = upload(client, teacher, sample("sample_a.xlsx")).json()
    url = f"/api/worksheets/previews/{preview['previewId']}/confirm"
    assert client.post(url, headers=teacher).status_code == 201
    again = client.post(url, headers=teacher)
    assert again.status_code == 409
    assert again.json()["error"]["message"] == "預覽已失效，請重新上傳"
    assert len(client.get("/api/worksheets", headers=teacher).json()["worksheets"]) == 1


def test_cancel_then_confirm_rejected(client, teacher):
    preview = upload(client, teacher, sample("sample_a.xlsx")).json()
    pid = preview["previewId"]
    assert client.delete(f"/api/worksheets/previews/{pid}", headers=teacher).status_code == 200
    assert client.post(f"/api/worksheets/previews/{pid}/confirm", headers=teacher).status_code == 409
    assert client.get("/api/worksheets", headers=teacher).json()["worksheets"] == []
    # 取消後可以重新選檔
    assert upload(client, teacher, sample("sample_a.xlsx")).status_code == 201


def test_preview_expires(client, teacher, clock):
    pid = upload(client, teacher, sample("sample_a.xlsx")).json()["previewId"]
    clock.advance(30 * 60)
    response = client.post(f"/api/worksheets/previews/{pid}/confirm", headers=teacher)
    assert response.json()["error"]["message"] == "預覽已失效，請重新上傳"


def test_restart_invalidates_preview_but_keeps_worksheets(make_client, password):
    first = make_client()
    headers = login(first, password)
    kept = upload(first, headers, sample("sample_a.xlsx")).json()
    first.post(f"/api/worksheets/previews/{kept['previewId']}/confirm", headers=headers)
    pending = upload(first, headers, sample("sample_b.xlsx")).json()

    second = make_client()
    headers2 = login(second, password)
    response = second.post(f"/api/worksheets/previews/{pending['previewId']}/confirm",
                           headers=headers2)
    assert response.status_code == 409
    listing = second.get("/api/worksheets", headers=headers2).json()["worksheets"]
    assert [w["questionCount"] for w in listing] == [6]
    detail = second.get(f"/api/worksheets/{listing[0]['id']}", headers=headers2).json()
    assert detail["questions"] == kept["questions"]


def test_same_file_can_be_imported_twice(client, teacher):
    for _ in range(2):
        pid = upload(client, teacher, sample("sample_a.xlsx")).json()["previewId"]
        client.post(f"/api/worksheets/previews/{pid}/confirm", headers=teacher)
    ids = [w["id"] for w in client.get("/api/worksheets", headers=teacher).json()["worksheets"]]
    assert len(ids) == 2 and ids[0] != ids[1]


def test_rejected_upload_returns_details_and_creates_nothing(client, teacher, data_dir):
    response = upload(client, teacher, builders.to_bytes(builders.multiple_errors()))
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "IMPORT_INVALID"
    assert error["message"] == "學習單有 2 處問題，未匯入"
    assert error["details"][0] == {"message": "工作表「學習單」第 7 列：作答欄沒有空白填空格",
                                   "sheet": "學習單", "location": "第 7 列"}
    assert client.get("/api/worksheets", headers=teacher).json()["worksheets"] == []
    assert list((data_dir / "worksheets").iterdir()) == []


@pytest.mark.parametrize("data,message", [
    (b"plain text", "檔案不是有效的 .xlsx 試算表或已損毀"),
    (b"", "檔案是空的"),
])
def test_invalid_uploads(client, teacher, data, message):
    response = upload(client, teacher, data)
    assert response.status_code == 400
    assert response.json()["error"]["message"] == message


def test_oversized_upload(client, teacher):
    response = upload(client, teacher, b"x" * (10 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()["error"]["message"] == "檔案超過大小上限（10 MB）"


def test_question_limit_from_settings(make_client, settings, password):
    client = make_client(settings_override=settings.model_copy(update={"max_questions": 10}))
    headers = login(client, password)
    response = upload(client, headers, builders.to_bytes(builders.many_questions(11)))
    assert response.json()["error"]["message"] == "題目數 11 超過上限 10"


def test_labels_from_settings(make_client, settings, password):
    custom = settings.model_copy(update={"label_no": "編號", "label_question": "問題",
                                         "label_answer": "回答"})
    client = make_client(settings_override=custom)
    headers = login(client, password)
    response = upload(client, headers, builders.to_bytes(builders.custom_labels()))
    assert response.status_code == 201 and response.json()["questionCount"] == 6


def test_missing_file_field(client, teacher):
    response = client.post("/api/worksheets/previews", headers=teacher, data={"x": "1"})
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "請選擇要上傳的檔案"


def test_unknown_worksheet(client, teacher):
    response = client.get("/api/worksheets/999", headers=teacher)
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "找不到學習單"


def test_upload_requires_teacher(client):
    response = upload(client, {}, sample("sample_a.xlsx"))
    assert response.status_code == 403
