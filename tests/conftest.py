from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.results.contract import FinalResultLookup

from .fake_google import FakeGoogleAuth, FakeSheetsGateway, sheet_url

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "http://127.0.0.1:8000"


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeResultSource:
    """測試用的最終結果來源。"""

    def __init__(self) -> None:
        self.results: dict[int, object] = {}
        self.not_ended: set[int] = set()

    def lookup(self, activity_id: int) -> FinalResultLookup:
        if activity_id in self.not_ended:
            return FinalResultLookup("not_ended")
        result = self.results.get(activity_id)
        if result is None:
            return FinalResultLookup("not_found")
        return FinalResultLookup("ended", result)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # 不讀取開發者本機的 BUZZER_* 環境變數
    for key in list(os.environ):
        if key.startswith("BUZZER_"):
            monkeypatch.delenv(key)

    # 任何測試都不可以真的連網（design.md D11）
    import requests

    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("測試不可連網")

    monkeypatch.setattr(requests.sessions.Session, "request", _blocked)


@pytest.fixture
def password() -> str:
    return secrets.token_urlsafe(18)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def settings(password: str, data_dir: Path) -> Settings:
    return Settings(_env_file=None, teacher_password=password, data_dir=data_dir, port=8000)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def results() -> FakeResultSource:
    return FakeResultSource()


@pytest.fixture
def gateway() -> FakeSheetsGateway:
    return FakeSheetsGateway()


@pytest.fixture
def google_auth() -> FakeGoogleAuth:
    return FakeGoogleAuth()


@pytest.fixture
def make_client(settings: Settings, clock: FakeClock, results: FakeResultSource,
                gateway: FakeSheetsGateway, google_auth: FakeGoogleAuth):
    clients: list[TestClient] = []

    def factory(*, settings_override: Settings | None = None, raise_server_exceptions: bool = True,
                gateway_override: object | None = None, google_auth_override: object | None = None
                ) -> TestClient:
        app = create_app(settings_override or settings, clock=clock, result_source=results,
                         gateway=gateway_override or gateway,  # type: ignore[arg-type]
                         google_auth=google_auth_override or google_auth)  # type: ignore[arg-type]
        client = TestClient(app, base_url=BASE_URL, raise_server_exceptions=raise_server_exceptions)
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.app.state.buzzer.db.close()
        client.close()


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


def register_window(client: TestClient) -> str:
    return client.post("/api/windows").json()["windowId"]


def login(client: TestClient, password: str, window_id: str | None = None) -> dict[str, str]:
    window_id = window_id or register_window(client)
    response = client.post("/api/teacher/login", json={"windowId": window_id, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture
def teacher(client: TestClient, password: str) -> dict[str, str]:
    return login(client, password)


def import_worksheet(client: TestClient, headers: dict[str, str], gateway: FakeSheetsGateway,
                     source: object, title: str = "測試學習單") -> int:
    """把活頁簿或 .xlsx 放進假的 Google，經由 API 匯入並確認，回傳學習單 ID。"""
    spreadsheet_id = gateway.add(source, title=title)
    preview = client.post("/api/worksheets/previews", headers=headers,
                          json={"url": sheet_url(spreadsheet_id)})
    assert preview.status_code == 201, preview.text
    confirmed = client.post(f"/api/worksheets/previews/{preview.json()['previewId']}/confirm",
                            headers=headers)
    assert confirmed.status_code == 201, confirmed.text
    return confirmed.json()["id"]


@pytest.fixture
def captured_logs(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    return caplog
