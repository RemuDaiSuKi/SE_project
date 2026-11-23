from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest

from app.google.auth import GoogleAuth
from app.google.gateway import GoogleSheetsGateway

from .conftest import FIXTURES, login, register_window
from .fake_google import FakeGoogleAuth, sheet_url
from .results_helpers import rec, result, single, units_for_sample_a
from .sheets_json import workbook_to_sheets_json

ROOT = Path(__file__).resolve().parent.parent

ACCESS_OLD = "ya29.OLD-access-token-abcdef"
ACCESS_NEW = "ya29.NEW-access-token-123456"
REFRESH = "1//refresh-token-zyxwvu"
CLIENT_SECRET = "GOCSPX-client-secret-qwerty"


class RefreshingCredentials:
    """過期的假憑證：refresh 後換成新的存取權杖。"""

    def __init__(self, info: dict) -> None:
        self.token = info["token"]
        self.refresh_token = info["refresh_token"]
        self.client_secret = info["client_secret"]
        self.valid = info.get("valid", False)

    def refresh(self, _request: object) -> None:
        self.token = ACCESS_NEW
        self.valid = True

    def to_json(self) -> str:
        return json.dumps({"token": self.token, "refresh_token": self.refresh_token,
                           "client_secret": self.client_secret, "valid": self.valid})


class RecordingSession:
    """模擬 Google Sheets API：GET 回傳試算表 JSON，POST 記錄寫入。"""

    def __init__(self, doc: dict) -> None:
        self.doc = doc
        self.posts: list[dict] = []
        self.tokens_seen: list[str] = []

    def request(self, method: str, url: str, **kwargs: object):
        class Response:
            status_code = 200

            def __init__(self, body: dict) -> None:
                self._body = body

            def json(self) -> dict:
                return self._body

        if method == "POST":
            self.posts.append(kwargs["json"])  # type: ignore[arg-type]
            return Response({"totalUpdatedCells": 1})
        return Response(self.doc)


def test_full_flow_never_logs_secrets(make_client, password, results, tmp_path, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    import openpyxl

    spreadsheet_id = "RealFlowSpreadsheet0000000001"
    doc = workbook_to_sheets_json(openpyxl.load_workbook(FIXTURES / "sample_a.xlsx"), spreadsheet_id)
    token_file = tmp_path / "google-token.json"
    token_file.write_text(json.dumps({"account": "teacher@example.com", "credentials": {
        "token": ACCESS_OLD, "refresh_token": REFRESH, "client_secret": CLIENT_SECRET}}),
        encoding="utf-8")
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps({"installed": {"client_secret": CLIENT_SECRET}}),
                           encoding="utf-8")
    auth = GoogleAuth(client_file, token_file, loader=RefreshingCredentials, request_factory=object)
    session = RecordingSession(doc)
    gateway = GoogleSheetsGateway(auth, session_factory=lambda creds: (
        session.tokens_seen.append(creds.token) or session))
    client = make_client(gateway_override=gateway, google_auth_override=auth)

    tokens: list[str] = []
    window = register_window(client)
    assert client.post("/api/teacher/login",
                       json={"windowId": window, "password": password + "x"}).status_code == 400
    login_response = client.post("/api/teacher/login", json={"windowId": window, "password": password})
    tokens.append(login_response.json()["token"])
    headers = {"Authorization": f"Bearer {tokens[0]}"}

    status = client.get("/api/google/status", headers=headers).json()
    assert status["authorized"] and status["account"] == "teacher@example.com"
    preview = client.post("/api/worksheets/previews", headers=headers,
                          json={"url": sheet_url(spreadsheet_id)}).json()
    ws_id = client.post(f"/api/worksheets/previews/{preview['previewId']}/confirm",
                        headers=headers).json()["id"]
    units = units_for_sample_a()
    units[0] = single(1, rec(1, 1, {1: "答案"}))
    results.results[1] = result(ws_id, *units)
    writeback = client.post("/api/activities/1/writeback", headers=headers).json()
    assert writeback["written"] == [1]
    assert session.posts[0]["valueInputOption"] == "RAW"
    assert client.get("/api/activities/1/results.csv", headers=headers).status_code == 200
    assert client.post("/api/teacher/logout", headers=headers).status_code == 200
    assert client.get("/api/worksheets", headers=headers).status_code == 401

    # 存取權杖確實被自動更新並保存
    assert session.tokens_seen[0] == ACCESS_NEW
    assert json.loads(token_file.read_text(encoding="utf-8"))["credentials"]["token"] == ACCESS_NEW

    captured = capsys.readouterr()
    everything = caplog.text + captured.out + captured.err
    assert "學習單已確認" in caplog.text and "Google 存取權杖已自動更新" in caplog.text
    for secret in [password, *tokens, ACCESS_OLD, ACCESS_NEW, REFRESH, CLIENT_SECRET]:
        assert secret not in everything


def _snapshot(client) -> tuple:
    db = client.app.state.buzzer.db
    with db.read() as conn:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("worksheets", "worksheet_questions", "worksheet_groups"))


TEACHER_ENDPOINTS = [
    ("GET", "/api/teacher/me"),
    ("POST", "/api/teacher/logout"),
    ("GET", "/api/google/status"),
    ("POST", "/api/worksheets/previews"),
    ("POST", "/api/worksheets/previews/{pid}/confirm"),
    ("DELETE", "/api/worksheets/previews/{pid}"),
    ("GET", "/api/worksheets"),
    ("GET", "/api/worksheets/1"),
    ("POST", "/api/activities/1/writeback"),
    ("GET", "/api/activities/1/results.csv"),
]


@pytest.mark.parametrize("method,path", TEACHER_ENDPOINTS)
@pytest.mark.parametrize("credential", ["none", "expired", "non_teacher"])
def test_permission_matrix(client, teacher, results, gateway, method, path, credential):
    sid = gateway.add(FIXTURES / "sample_a.xlsx")
    pid = client.post("/api/worksheets/previews", headers=teacher,
                      json={"url": sheet_url(sid)}).json()["previewId"]
    results.results[1] = result(1, *units_for_sample_a())
    state = client.app.state.buzzer
    if credential == "none":
        headers, status = {}, 403
    elif credential == "expired":
        token = state.sessions.issue("teacher", "w")
        state.sessions.revoke(token)
        headers, status = {"Authorization": f"Bearer {token}"}, 401
    else:
        token = state.sessions.issue("group", "w", group_id=1)
        headers, status = {"Authorization": f"Bearer {token}"}, 403

    before = _snapshot(client)
    fetches_before, writes_before = gateway.fetch_count, len(gateway.writes)
    response = client.request(method, path.format(pid=pid), headers=headers,
                              json={"url": sheet_url(sid)})
    assert response.status_code == status
    expected = "無權限執行此操作" if status == 403 else "登入已失效，請重新登入"
    assert response.json()["error"]["message"] == expected
    assert "teacher@example.com" not in response.text
    assert _snapshot(client) == before
    assert (gateway.fetch_count, len(gateway.writes)) == (fetches_before, writes_before)
    # 被拒絕的請求沒有消耗或取消預覽
    assert client.post(f"/api/worksheets/previews/{pid}/confirm", headers=teacher).status_code == 201


def test_unauthorized_google_import_message(make_client, password, gateway):
    from app.google.errors import SheetsError

    client = make_client(google_auth_override=FakeGoogleAuth(authorized=False))
    headers = login(client, password)
    gateway.fetch_error = SheetsError("not_authorized")
    response = client.post("/api/worksheets/previews", headers=headers,
                           json={"url": sheet_url(gateway.add(FIXTURES / "sample_a.xlsx"))})
    assert response.json()["error"]["message"] == "尚未完成 Google 授權，請先執行 python -m app google-login"


def test_env_example_and_gitignore():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "BUZZER_TEACHER_PASSWORD=change-me" in example
    assert "BUZZER_GOOGLE_TIMEOUT_SECONDS" in example
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in (".env", "data/", "client_secret*.json", "google-client-secret*.json",
                    "google-token*.json"):
        assert pattern in ignored


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    """執行 git；沒有安裝 git 時跳過測試。"""
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8")
    except FileNotFoundError:
        pytest.skip("git 不可用")


def test_no_secret_files_tracked_or_unignored():
    proc = _git("ls-files", "--others", "--cached", "--exclude-standard")
    if proc.returncode != 0:
        pytest.skip("git 不可用")
    files = proc.stdout.splitlines()
    assert ".env" not in files
    assert not any(f.startswith("data/") for f in files)
    assert not any(Path(f).name.startswith(("client_secret", "google-token", "google-client-secret"))
                   for f in files)


def test_google_credential_filename_is_ignored():
    proc = _git("check-ignore", "client_secret_123-abc.apps.googleusercontent.com.json")
    if proc.returncode not in (0, 1):
        pytest.skip("git 不可用")
    assert proc.returncode == 0
