from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from .conftest import FIXTURES, register_window
from .results_helpers import rec, result, single, units_for_sample_a

ROOT = Path(__file__).resolve().parent.parent


def test_full_flow_never_logs_secrets(client, password, results, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    tokens: list[str] = []

    window = register_window(client)
    assert client.post("/api/teacher/login",
                       json={"windowId": window, "password": password + "x"}).status_code == 400
    login = client.post("/api/teacher/login", json={"windowId": window, "password": password})
    token = login.json()["token"]
    tokens.append(token)
    headers = {"Authorization": f"Bearer {token}"}

    data = (FIXTURES / "sample_a.xlsx").read_bytes()
    preview = client.post("/api/worksheets/previews", headers=headers,
                          files={"file": ("a.xlsx", data, "application/octet-stream")}).json()
    ws_id = client.post(f"/api/worksheets/previews/{preview['previewId']}/confirm",
                        headers=headers).json()["id"]
    units = units_for_sample_a()
    units[0] = single(1, rec(1, 1, {1: "答案"}))
    results.results[1] = result(ws_id, *units)
    assert client.post("/api/activities/1/writeback", headers=headers).status_code == 200
    assert client.get("/api/activities/1/results.csv", headers=headers).status_code == 200
    assert client.post("/api/teacher/logout", headers=headers).status_code == 200
    # 失效 Token 再呼叫一次
    assert client.get("/api/worksheets", headers=headers).status_code == 401

    captured = capsys.readouterr()
    everything = caplog.text + captured.out + captured.err
    assert "學習單已確認" in caplog.text  # 確實有記錄事件
    for secret in [password, *tokens]:
        assert secret not in everything


def _setup_preview(client, headers) -> str:
    data = (FIXTURES / "sample_a.xlsx").read_bytes()
    return client.post("/api/worksheets/previews", headers=headers,
                       files={"file": ("a.xlsx", data, "application/octet-stream")}).json()["previewId"]


def _snapshot(client, data_dir: Path) -> tuple:
    db = client.app.state.buzzer.db
    with db.read() as conn:
        counts = tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                       for t in ("worksheets", "worksheet_questions", "worksheet_groups"))
    files = tuple(sorted(p.name for p in (data_dir / "worksheets").iterdir()))
    return counts, files


TEACHER_ENDPOINTS = [
    ("GET", "/api/teacher/me"),
    ("POST", "/api/teacher/logout"),
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
def test_permission_matrix(client, teacher, results, data_dir, clock, method, path, credential):
    pid = _setup_preview(client, teacher)
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

    before = _snapshot(client, data_dir)
    kwargs = {}
    if path == "/api/worksheets/previews":
        kwargs["files"] = {"file": ("a.xlsx", (FIXTURES / "sample_a.xlsx").read_bytes(),
                                    "application/octet-stream")}
    response = client.request(method, path.format(pid=pid), headers=headers, **kwargs)
    assert response.status_code == status
    expected = "無權限執行此操作" if status == 403 else "登入已失效，請重新登入"
    assert response.json()["error"]["message"] == expected
    assert _snapshot(client, data_dir) == before
    # 被拒絕的請求沒有消耗或取消預覽
    assert client.post(f"/api/worksheets/previews/{pid}/confirm", headers=teacher).status_code == 201


def test_env_example_and_gitignore():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "BUZZER_TEACHER_PASSWORD=change-me" in example
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored and "data/" in ignored


def test_no_env_file_tracked_or_unignored():
    proc = subprocess.run(["git", "ls-files", "--others", "--cached", "--exclude-standard"],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        pytest.skip("git 不可用")
    files = proc.stdout.splitlines()
    assert ".env" not in files
    assert not any(f.startswith("data/") for f in files)
