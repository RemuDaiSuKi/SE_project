from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from google.auth.exceptions import RefreshError, TransportError

from app.config import Settings
from app.google.auth import AuthStatus, GoogleAuth, save_token, startup_problem
from app.google.errors import MESSAGES, SheetsError
from app.google.gateway import FETCH_FIELDS, CellWrite, GoogleSheetsGateway, classify_response
from app.google.login import run_login
from app.google.urls import canonical_url, parse_spreadsheet_id

SHEET_ID = "1PXXwWiBKJNpPkLRoJLMzZWsAh4Jzn2bThHTeRAiq3Hg"

# ---------------------------------------------------------------- URLs


@pytest.mark.parametrize("text,expected", [
    (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0", SHEET_ID),
    (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}", SHEET_ID),
    (f"  https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?usp=sharing  ", SHEET_ID),
    (SHEET_ID, SHEET_ID),
    # 規則與 SpecKit 組一致：只接受 https://docs.google.com/spreadsheets/d/ 開頭的網址或純 ID
    (f"https://docs.google.com/spreadsheets/u/1/d/{SHEET_ID}/edit", None),
    (f"http://docs.google.com/spreadsheets/d/{SHEET_ID}/edit", None),
    (f"https://example.com/spreadsheets/d/{SHEET_ID}", None),
    ("https://docs.google.com/spreadsheets/d/e/2PACX-1vabcdefghijklmnopqrstuvwxyz/pubhtml", None),
    ("https://example.com/abc", None),
    ("short-id", None),
    ("a" * 101, None),
    (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#" + "x" * 2100, None),
    ("", None),
    ("   ", None),
    (None, None),
])
def test_parse_spreadsheet_id(text, expected):
    assert parse_spreadsheet_id(text) == expected


def test_canonical_url():
    assert canonical_url(SHEET_ID) == f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"


# ---------------------------------------------------------------- auth


class FakeCredentials:
    """模擬 google.oauth2.credentials.Credentials 的必要介面。"""

    refresh_calls = 0

    def __init__(self, info: dict) -> None:
        self.token = info.get("token")
        self.refresh_token = info.get("refresh_token")
        self.valid = bool(info.get("valid"))
        self.fail = info.get("fail")

    def refresh(self, _request: object) -> None:
        FakeCredentials.refresh_calls += 1
        if self.fail == "refresh":
            raise RefreshError("invalid_grant")
        if self.fail == "transport":
            raise TransportError("offline")
        self.token = "new-access-token-" + str(FakeCredentials.refresh_calls)
        self.valid = True

    def to_json(self) -> str:
        return json.dumps({"token": self.token, "refresh_token": self.refresh_token,
                           "valid": self.valid, "fail": self.fail})


def _auth(tmp_path: Path, info: dict | None, *, client: bool = True) -> GoogleAuth:
    client_path = tmp_path / "client.json"
    token_path = tmp_path / "token.json"
    if client:
        client_path.write_text("{}", encoding="utf-8")
    if info is not None:
        token_path.write_text(json.dumps({"account": "t@example.com", "credentials": info}),
                              encoding="utf-8")
    return GoogleAuth(client_path, token_path, loader=FakeCredentials, request_factory=object)


def test_not_authorized_when_token_missing(tmp_path):
    auth = _auth(tmp_path, None)
    with pytest.raises(SheetsError) as info:
        auth.credentials()
    assert info.value.kind == "not_authorized"
    status = auth.status()
    assert (status.configured, status.authorized, status.account) == (True, False, None)


def test_status_without_client_file(tmp_path):
    status = _auth(tmp_path, None, client=False).status()
    assert status.configured is False and status.authorized is False


def test_valid_credentials_returned_without_refresh(tmp_path):
    auth = _auth(tmp_path, {"token": "a", "refresh_token": "r", "valid": True})
    assert auth.credentials().token == "a"
    status = auth.status()
    assert (status.authorized, status.account) == (True, "t@example.com")


def test_expired_credentials_refreshed_and_saved(tmp_path):
    auth = _auth(tmp_path, {"token": "old", "refresh_token": "r", "valid": False})
    creds = auth.credentials()
    assert creds.token.startswith("new-access-token")
    saved = json.loads((tmp_path / "token.json").read_text(encoding="utf-8"))
    assert saved["credentials"]["token"] == creds.token and saved["account"] == "t@example.com"
    assert not (tmp_path / "token.json.tmp").exists()


def test_refresh_failure_is_auth_expired(tmp_path):
    auth = _auth(tmp_path, {"token": "old", "refresh_token": "r", "valid": False, "fail": "refresh"})
    with pytest.raises(SheetsError) as info:
        auth.credentials()
    assert info.value.kind == "auth_expired"


def test_refresh_network_failure(tmp_path):
    auth = _auth(tmp_path, {"refresh_token": "r", "valid": False, "fail": "transport"})
    with pytest.raises(SheetsError) as info:
        auth.credentials()
    assert info.value.kind == "unavailable"


def test_account_for_error_messages(tmp_path):
    auth = _auth(tmp_path, None)
    assert auth.account() is None
    save_token(tmp_path / "token.json", FakeCredentials({"token": "a", "refresh_token": "r",
                                                         "valid": True}), "t@example.com")
    assert auth.account() == "t@example.com"


def test_startup_problem():
    hint = "python -m app google-login"
    missing = startup_problem(AuthStatus(False, False, None), "BUZZER_GOOGLE_CLIENT_SECRETS", hint)
    assert "找不到 Google OAuth 用戶端設定檔（BUZZER_GOOGLE_CLIENT_SECRETS），伺服器無法啟動" in missing
    assert startup_problem(AuthStatus(True, False, None), "X", hint) == \
        "尚未完成 Google 授權，伺服器無法啟動。請先執行 python -m app google-login"
    assert startup_problem(AuthStatus(True, True, "t@example.com"), "X", hint) is None


def test_missing_refresh_token_is_auth_expired(tmp_path):
    with pytest.raises(SheetsError) as info:
        _auth(tmp_path, {"token": "old", "valid": False}).credentials()
    assert info.value.kind == "auth_expired"


def test_corrupt_token_file_treated_as_not_authorized(tmp_path):
    auth = _auth(tmp_path, None)
    (tmp_path / "token.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SheetsError) as info:
        auth.credentials()
    assert info.value.kind == "not_authorized"


def test_token_file_reloaded_after_login(tmp_path):
    auth = _auth(tmp_path, None)
    assert auth.status().authorized is False
    save_token(tmp_path / "token.json", FakeCredentials({"token": "x", "refresh_token": "r",
                                                         "valid": True}), "new@example.com")
    assert auth.status().account == "new@example.com"


# ---------------------------------------------------------------- gateway


class FakeResponse:
    def __init__(self, status: int, body: object = None) -> None:
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self) -> object:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeSession:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response  # type: ignore[return-value]


class StubAuth:
    def __init__(self, error: SheetsError | None = None,
                 account: str | None = "teacher@example.com") -> None:
        self.error = error
        self._account = account

    def credentials(self) -> object:
        if self.error:
            raise self.error
        return "creds"

    def account(self) -> str | None:
        return self._account


def _gateway(response: object, auth: StubAuth | None = None) -> tuple[GoogleSheetsGateway, FakeSession]:
    session = FakeSession(response)
    gateway = GoogleSheetsGateway(auth or StubAuth(), timeout_seconds=7,  # type: ignore[arg-type]
                                  session_factory=lambda _creds: session)
    return gateway, session


def test_fetch_request_and_conversion():
    body = {"spreadsheetId": SHEET_ID, "properties": {"title": "範例"},
            "sheets": [{"properties": {"sheetId": 3, "title": "學習單"},
                        "data": [{"rowData": [{"values": [{"formattedValue": "x"}]}]}]}]}
    gateway, session = _gateway(FakeResponse(200, body))
    grid = gateway.fetch(SHEET_ID)
    method, url, kwargs = session.calls[0]
    assert method == "GET" and url.endswith(f"/v4/spreadsheets/{SHEET_ID}")
    assert kwargs["params"] == {"includeGridData": "true", "fields": FETCH_FIELDS}
    assert kwargs["timeout"] == 7
    assert grid.title == "範例" and grid.sheets[0].values == {(1, 1): "x"}


def test_write_cells_single_raw_batch_with_quoted_titles():
    gateway, session = _gateway(FakeResponse(200, {"totalUpdatedCells": 2}))
    gateway.write_cells(SHEET_ID, [CellWrite("學習單", "H5", "=1+1"),
                                   CellWrite("老師's 表", "G7", "a\nb")])
    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "POST" and url.endswith(f"/{SHEET_ID}/values:batchUpdate")
    assert kwargs["json"] == {"valueInputOption": "RAW", "data": [
        {"range": "'學習單'!H5", "values": [["=1+1"]]},
        {"range": "'老師''s 表'!G7", "values": [["a\nb"]]},
    ]}


def test_write_cells_noop_when_empty():
    gateway, session = _gateway(FakeResponse(200))
    gateway.write_cells(SHEET_ID, [])
    assert session.calls == []


@pytest.mark.parametrize("status,body,kind", [
    (401, {}, "auth_expired"),
    (404, {"error": {"status": "NOT_FOUND", "message": "Requested entity was not found."}}, "not_found"),
    (403, {"error": {"status": "PERMISSION_DENIED", "message": "The caller does not have permission"}},
     "forbidden"),
    # 與 SpecKit 組一致：403 一律是沒有權限，其他非 401/404 的錯誤一律是暫時無法使用
    (403, {"error": {"status": "PERMISSION_DENIED",
                     "details": [{"reason": "SERVICE_DISABLED"}]}}, "forbidden"),
    (403, {"error": {"errors": [{"reason": "accessNotConfigured"}]}}, "forbidden"),
    (400, {"error": {"status": "FAILED_PRECONDITION",
                     "message": "This operation is not supported for this document"}}, "unavailable"),
    (400, {"error": {"status": "INVALID_ARGUMENT"}}, "unavailable"),
    (429, {}, "unavailable"),
    (503, ValueError("not json"), "unavailable"),
])
def test_error_classification(status, body, kind):
    with pytest.raises(SheetsError) as info:
        classify_response(FakeResponse(status, body))
    assert info.value.kind == kind
    # 訊息只來自固定的繁中訊息，不含 Google 原始內容
    assert "permission" not in info.value.message.lower()
    assert info.value.message == MESSAGES[kind][1].format(account="")


def test_forbidden_message_names_account():
    with pytest.raises(SheetsError) as info:
        classify_response(FakeResponse(403, {}), "teacher@example.com")
    assert info.value.message == (
        "目前登入的 Google 帳號（teacher@example.com）沒有這份試算表的編輯權限，"
        "請改用有權限的帳號重新登入，或請擁有者把試算表共用給這個帳號（編輯者）")


def test_gateway_forbidden_uses_authorized_account():
    gateway, _ = _gateway(FakeResponse(403, {}), StubAuth(account="owner@example.com"))
    with pytest.raises(SheetsError) as info:
        gateway.fetch(SHEET_ID)
    assert "（owner@example.com）" in info.value.message


@pytest.mark.parametrize("exc,kind", [
    (requests.exceptions.ConnectionError("down"), "unavailable"),
    (requests.exceptions.Timeout("slow"), "unavailable"),
    (TransportError("dns"), "unavailable"),
    (RefreshError("revoked"), "auth_expired"),
])
def test_transport_errors(exc, kind):
    gateway, _ = _gateway(exc)
    with pytest.raises(SheetsError) as info:
        gateway.fetch(SHEET_ID)
    assert info.value.kind == kind


def test_auth_errors_propagate_before_any_request():
    gateway, session = _gateway(FakeResponse(200), StubAuth(SheetsError("not_authorized")))
    with pytest.raises(SheetsError) as info:
        gateway.fetch(SHEET_ID)
    assert info.value.kind == "not_authorized" and session.calls == []


# ---------------------------------------------------------------- login command


class FakeFlow:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.kwargs: dict = {}

    def run_local_server(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _settings(tmp_path: Path, *, with_client: bool = True) -> Settings:
    client = tmp_path / "client_secret.json"
    if with_client:
        client.write_text('{"installed": {}}', encoding="utf-8")
    return Settings(_env_file=None, data_dir=tmp_path / "data", google_client_secrets=client)


def test_login_missing_client_file(tmp_path):
    err = io.StringIO()
    called = []
    code = run_login(_settings(tmp_path, with_client=False), err=err, out=io.StringIO(),
                     flow_factory=lambda *a: called.append(a))
    assert code == 1 and called == []
    assert "找不到 Google OAuth 用戶端設定檔（BUZZER_GOOGLE_CLIENT_SECRETS）" in err.getvalue()


def test_login_success_saves_token_and_binds_loopback(tmp_path):
    settings = _settings(tmp_path)
    creds = FakeCredentials({"token": "ya29.access-token-xyz", "refresh_token": "1//refresh-xyz",
                             "valid": True})
    flow = FakeFlow(creds)
    out, err = io.StringIO(), io.StringIO()
    code = run_login(settings, flow_factory=lambda path, scopes: flow,
                     account_fetcher=lambda _c: "teacher@example.com", out=out, err=err)
    assert code == 0
    assert flow.kwargs["bind_addr"] == "127.0.0.1" and flow.kwargs["port"] == 0
    saved = json.loads(settings.google_token_path.read_text(encoding="utf-8"))
    assert saved["account"] == "teacher@example.com"
    assert saved["credentials"]["refresh_token"] == "1//refresh-xyz"
    assert "已完成 Google 授權：teacher@example.com" in out.getvalue()
    printed = out.getvalue() + err.getvalue()
    assert "ya29.access-token-xyz" not in printed and "1//refresh-xyz" not in printed


@pytest.mark.parametrize("outcome", [RuntimeError("access_denied"), TimeoutError(), None,
                                     SimpleNamespace(refresh_token=None)])
def test_login_not_completed_keeps_existing_token(tmp_path, outcome):
    settings = _settings(tmp_path)
    settings.google_token_path.parent.mkdir(parents=True)
    settings.google_token_path.write_text("ORIGINAL", encoding="utf-8")
    err = io.StringIO()
    code = run_login(settings, flow_factory=lambda *a: FakeFlow(outcome),
                     account_fetcher=lambda _c: "x", out=io.StringIO(), err=err)
    assert code == 1
    assert "Google 授權未完成" in err.getvalue()
    assert settings.google_token_path.read_text(encoding="utf-8") == "ORIGINAL"
