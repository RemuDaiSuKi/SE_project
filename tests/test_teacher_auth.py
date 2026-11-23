from __future__ import annotations

from app.security import (
    ROLE_TEACHER,
    LoginLimiter,
    SessionStore,
    WindowRegistry,
    bearer_token,
    password_matches,
)

from .conftest import FakeClock, login, register_window

# ---------------------------------------------------------------- unit


def test_lockout_after_max_failures_and_expiry():
    clock = FakeClock()
    windows = WindowRegistry(max_failures=5, lock_seconds=60, clock=clock)
    w1, w2 = windows.register(), windows.register()
    for _ in range(4):
        windows.record_failure(w1)
    assert windows.lock_remaining(w1) == 0
    windows.record_failure(w1)
    assert windows.lock_remaining(w1) == 60
    assert windows.lock_remaining(w2) == 0
    clock.advance(59.5)
    assert windows.lock_remaining(w1) == 1
    clock.advance(0.5)
    assert windows.lock_remaining(w1) == 0
    # 鎖定解除後重新計數
    windows.record_failure(w1)
    assert windows.lock_remaining(w1) == 0


def test_success_resets_failures():
    windows = WindowRegistry(max_failures=3, lock_seconds=60, clock=FakeClock())
    window = windows.register()
    windows.record_failure(window)
    windows.record_failure(window)
    windows.record_success(window)
    windows.record_failure(window)
    windows.record_failure(window)
    assert windows.lock_remaining(window) == 0


def test_login_limiter_is_global_and_resets():
    clock = FakeClock()
    limiter = LoginLimiter(max_failures=5, lock_seconds=300, clock=clock)
    for _ in range(4):
        limiter.record_failure()
    assert limiter.lock_remaining() == 0
    limiter.record_success()  # 成功歸零
    for _ in range(4):
        limiter.record_failure()
    assert limiter.lock_remaining() == 0
    limiter.record_failure()
    assert limiter.lock_remaining() == 300
    clock.advance(299.5)
    assert limiter.lock_remaining() == 1
    clock.advance(0.5)
    assert limiter.lock_remaining() == 0
    limiter.record_failure()  # 鎖定時計數已歸零，重新計算
    assert limiter.lock_remaining() == 0


def test_token_expiry_and_revoke():
    clock = FakeClock()
    sessions = SessionStore(ttl_seconds=100, clock=clock)
    token = sessions.issue(ROLE_TEACHER, "w")
    assert sessions.resolve(token).role == ROLE_TEACHER
    assert token not in repr(sessions._sessions)  # 只保存雜湊
    clock.advance(100)
    assert sessions.resolve(token) is None
    token2 = sessions.issue(ROLE_TEACHER, "w")
    sessions.revoke(token2)
    assert sessions.resolve(token2) is None


def test_helpers():
    assert password_matches("abc", "abc") and not password_matches("abc", "abd")
    assert bearer_token("Bearer xyz") == "xyz"
    assert bearer_token("Basic xyz") is None and bearer_token(None) is None


# ---------------------------------------------------------------- API


def _login(client, window, password):
    return client.post("/api/teacher/login", json={"windowId": window, "password": password})


def test_login_success_and_me(client, password):
    window = register_window(client)
    response = _login(client, window, password)
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "teacher" and body["token"]
    me = client.get("/api/teacher/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200


def test_wrong_password(client):
    response = _login(client, register_window(client), "wrong")
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "密碼錯誤"
    assert "token" not in response.json()


def test_lockout_shared_by_all_windows(client, password, clock):
    # 與 SpecKit 組一致：老師登入的失敗次數全體共用，連續 5 次鎖定 300 秒
    w1, w2 = register_window(client), register_window(client)
    for _ in range(3):
        assert _login(client, w1, "wrong").status_code == 400
    for _ in range(2):
        assert _login(client, w2, "wrong").status_code == 400
    locked = _login(client, w1, password)
    assert locked.status_code == 429
    error = locked.json()["error"]
    assert error["code"] == "LOCKED" and error["retryAfterSeconds"] == 300
    assert error["message"] == "密碼錯誤次數過多，請於 300 秒後再試"
    assert locked.headers["retry-after"] == "300"
    # 其他視窗也被鎖定
    assert _login(client, w2, password).status_code == 429
    clock.advance(300)
    assert _login(client, w2, password).status_code == 200


def test_login_lock_configurable(make_client, settings, password, clock):
    client = make_client(settings_override=settings.model_copy(
        update={"login_max_failures": 2, "login_lock_seconds": 30}))
    window = register_window(client)
    for _ in range(2):
        _login(client, window, "wrong")
    assert _login(client, window, password).json()["error"]["retryAfterSeconds"] == 30


def test_unknown_window(client, password):
    response = _login(client, "not-issued", password)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WINDOW_UNKNOWN"


def test_logout_only_affects_that_window(client, password):
    a = login(client, password)
    b = login(client, password)
    assert client.post("/api/teacher/logout", headers=a).status_code == 200
    expired = client.get("/api/teacher/me", headers=a)
    assert expired.status_code == 401
    assert expired.json()["error"]["message"] == "登入已失效，請重新登入"
    assert client.get("/api/teacher/me", headers=b).status_code == 200


def test_token_ttl(client, password, clock, settings):
    headers = login(client, password)
    clock.advance(settings.token_ttl_seconds)
    assert client.get("/api/teacher/me", headers=headers).status_code == 401


def test_restart_invalidates_tokens(make_client, password):
    first = make_client()
    headers = login(first, password)
    second = make_client()  # 同一資料目錄重新建立 app = 伺服器重啟
    response = second.get("/api/worksheets", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "登入已失效，請重新登入"


def test_no_token_is_forbidden(client):
    response = client.get("/api/worksheets")
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "無權限執行此操作"


def test_non_teacher_token_is_forbidden(client):
    window = register_window(client)
    token = client.app.state.buzzer.sessions.issue("group", window, group_id=1)
    response = client.get("/api/worksheets", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "無權限執行此操作"


def test_no_cookies_used(client, password):
    window = register_window(client)
    response = _login(client, window, password)
    assert "set-cookie" not in response.headers
