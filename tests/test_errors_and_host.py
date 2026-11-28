from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.errors import GENERIC_ERROR_MESSAGE

from .conftest import BASE_URL


def test_validation_error_is_chinese(client):
    response = client.post("/api/teacher/login", json={"password": 123})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error == {"code": "BAD_REQUEST", "message": "請求格式不正確"}


def test_unknown_path_is_chinese(client):
    response = client.get("/api/no-such-thing")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "找不到資源"


def test_method_not_allowed_is_chinese(client):
    response = client.put("/api/windows")
    assert response.status_code == 405
    assert response.json()["error"]["message"] == "不支援的請求方法"


def test_unexpected_error_hides_internals(make_client, teacher, monkeypatch):
    client = make_client(raise_server_exceptions=False)
    # 重新登入以取得此 client 的 Token
    from .conftest import login

    headers = login(client, client.app.state.buzzer.settings.teacher_password.get_secret_value())

    def boom(*_a, **_k):
        raise RuntimeError("secret internal path C:\\data\\buzzer.db")

    monkeypatch.setattr(client.app.state.buzzer.worksheets, "list", boom)
    response = client.get("/api/worksheets", headers=headers)
    assert response.status_code == 500
    body = response.text
    assert response.json()["error"]["message"] == GENERIC_ERROR_MESSAGE
    for leaked in ("RuntimeError", "Traceback", "buzzer.db", "secret internal"):
        assert leaked not in body


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000", "192.168.0.5:8000"])
def test_host_header_not_checked(client, host):
    # 與 SpecKit 組一致：不檢查 Host 標頭，連線範圍由監聽位址（BUZZER_HOST）決定
    response = client.post("/api/windows", headers={"host": host})
    assert response.status_code == 201


def test_api_responses_not_cached(client):
    assert client.post("/api/windows").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/", "/teacher", "/static/js/teacher.js", "/static/js/api.js",
                                  "/static/js/student.js", "/static/css/app.css"])
def test_pages_and_assets_revalidate(client, path):
    # 瀏覽器每次使用快取前都要先向伺服器確認有沒有新版
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_unchanged_asset_returns_304(client):
    first = client.get("/static/js/teacher.js")
    etag = first.headers["etag"]
    second = client.get("/static/js/teacher.js", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["cache-control"] == "no-cache"


def test_pages_served(client):
    assert client.get("/").status_code == 200
    teacher = client.get("/teacher")
    assert teacher.status_code == 200 and "老師登入" in teacher.text
    assert client.get("/static/js/api.js").status_code == 200


def test_testclient_base_url():
    assert BASE_URL.startswith("http://127.0.0.1:")
