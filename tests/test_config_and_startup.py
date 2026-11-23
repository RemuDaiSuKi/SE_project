from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.__main__ import build_server_config
from app.config import DEFAULT_HOST, Settings, StartupError, invalid_setting_names
from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent


def test_defaults():
    s = Settings(_env_file=None)
    assert s.port == 8000
    assert s.max_questions == 500
    assert (s.label_no, s.label_question, s.label_answer) == ("題號", "題目", "作答")
    assert s.login_max_failures == 5 and s.login_lock_seconds == 300
    assert s.lockout_max_failures == 5 and s.lockout_seconds == 60 and s.token_ttl_hours == 8
    assert s.host == DEFAULT_HOST == "127.0.0.1"
    assert s.teacher_password is None and not s.has_teacher_password()
    assert s.google_client_secrets_path == Path("data") / "google-client-secret.json"
    assert s.google_token_path == Path("data") / "google-token.json"
    assert s.google_timeout_seconds == 10
    assert not hasattr(s, "max_upload_mb")


def test_google_paths_follow_data_dir_and_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert s.google_client_secrets_path == tmp_path / "google-client-secret.json"
    monkeypatch.setenv("BUZZER_GOOGLE_CLIENT_SECRETS", str(tmp_path / "x" / "client_secret_1.json"))
    monkeypatch.setenv("BUZZER_GOOGLE_TOKEN_FILE", str(tmp_path / "tok.json"))
    monkeypatch.setenv("BUZZER_GOOGLE_TIMEOUT_SECONDS", "5")
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert s.google_client_secrets_path == tmp_path / "x" / "client_secret_1.json"
    assert s.google_token_path == tmp_path / "tok.json"
    assert s.google_timeout_seconds == 5


def test_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("BUZZER_PORT", "9100")
    monkeypatch.setenv("BUZZER_MAX_QUESTIONS", "10")
    monkeypatch.setenv("BUZZER_LABEL_ANSWER", " 回答 ")
    monkeypatch.setenv("BUZZER_DATA_DIR", str(tmp_path))
    s = Settings(_env_file=None)
    assert s.port == 9100 and s.max_questions == 10 and s.label_answer == "回答"
    assert s.data_dir == tmp_path


@pytest.mark.parametrize("field,value,env", [
    ("port", "abc", "BUZZER_PORT"),
    ("port", "70000", "BUZZER_PORT"),
    ("max_questions", "0", "BUZZER_MAX_QUESTIONS"),
    ("label_no", "   ", "BUZZER_LABEL_NO"),
    ("google_timeout_seconds", "0", "BUZZER_GOOGLE_TIMEOUT_SECONDS"),
    ("host", "  ", "BUZZER_HOST"),
    ("login_lock_seconds", "0", "BUZZER_LOGIN_LOCK_SECONDS"),
])
def test_invalid_values_report_setting_name(field, value, env):
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None, **{field: value})
    names = invalid_setting_names(info.value)
    assert names == [env]


def test_duplicate_labels_rejected():
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None, label_no="題目")
    assert "BUZZER_LABEL_NO" in invalid_setting_names(info.value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_create_app_refuses_without_password(value, tmp_path):
    with pytest.raises(StartupError, match="BUZZER_TEACHER_PASSWORD"):
        create_app(Settings(_env_file=None, teacher_password=value, data_dir=tmp_path))


def _run_main(env_updates: dict[str, str], tmp_path: Path,
              args: list[str] | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("BUZZER_")}
    # PYTHONPATH 讓子程序能 import 專案的 app 套件；cwd 在暫存目錄，不會讀到專案的 .env
    env.update({"PYTHONIOENCODING": "utf-8", "BUZZER_DATA_DIR": str(tmp_path / "data"),
                "PYTHONPATH": str(ROOT)})
    env.update(env_updates)
    return subprocess.run([sys.executable, "-m", "app", *(args or [])], cwd=tmp_path, env=env,
                          capture_output=True, timeout=60)


def test_main_exits_when_password_missing(tmp_path):
    proc = _run_main({}, tmp_path)
    stderr = proc.stderr.decode("utf-8")
    assert proc.returncode == 1
    assert "未設定老師密碼（BUZZER_TEACHER_PASSWORD），伺服器無法啟動" in stderr


def test_main_exits_when_password_blank(tmp_path):
    proc = _run_main({"BUZZER_TEACHER_PASSWORD": "   "}, tmp_path)
    assert proc.returncode == 1
    assert "BUZZER_TEACHER_PASSWORD" in proc.stderr.decode("utf-8")


def test_main_exits_on_invalid_setting_without_leaking_values(tmp_path):
    secret = "pw-should-not-appear-123"
    proc = _run_main({"BUZZER_TEACHER_PASSWORD": secret, "BUZZER_PORT": "abc"}, tmp_path)
    output = (proc.stdout + proc.stderr).decode("utf-8")
    assert proc.returncode == 1
    assert "設定不合法" in output and "BUZZER_PORT" in output
    assert secret not in output and "abc" not in output


def test_unknown_command(tmp_path):
    proc = _run_main({"BUZZER_TEACHER_PASSWORD": "x"}, tmp_path, args=["no-such-command"])
    assert proc.returncode == 2
    assert "未知的指令" in proc.stderr.decode("utf-8")


def test_google_login_command_without_client_file(tmp_path):
    # 登入指令不需要老師密碼；缺少用戶端設定檔時不開啟瀏覽器
    proc = _run_main({}, tmp_path, args=["google-login"])
    assert proc.returncode == 1
    assert "找不到 Google OAuth 用戶端設定檔（BUZZER_GOOGLE_CLIENT_SECRETS）" in proc.stderr.decode("utf-8")


def test_main_refuses_without_google_client_file(tmp_path):
    # 與 SpecKit 組一致：缺少 OAuth 用戶端設定檔時伺服器拒絕啟動
    proc = _run_main({"BUZZER_TEACHER_PASSWORD": "x"}, tmp_path)
    stderr = proc.stderr.decode("utf-8")
    assert proc.returncode == 1
    assert "找不到 Google OAuth 用戶端設定檔（BUZZER_GOOGLE_CLIENT_SECRETS），伺服器無法啟動" in stderr
    assert "python -m app google-login" in stderr


def test_main_refuses_without_google_authorization(tmp_path):
    client = tmp_path / "client_secret.json"
    client.write_text('{"installed": {}}', encoding="utf-8")
    proc = _run_main({"BUZZER_TEACHER_PASSWORD": "x", "BUZZER_GOOGLE_CLIENT_SECRETS": str(client)},
                     tmp_path)
    assert proc.returncode == 1
    assert "尚未完成 Google 授權，伺服器無法啟動。請先執行 python -m app google-login" in \
        proc.stderr.decode("utf-8")


def test_password_checked_before_google(tmp_path):
    proc = _run_main({}, tmp_path)
    stderr = proc.stderr.decode("utf-8")
    assert "BUZZER_TEACHER_PASSWORD" in stderr and "Google" not in stderr


def test_server_config_single_process(settings):
    app = create_app(settings)
    config = build_server_config(app, settings)
    assert config.host == "127.0.0.1"
    assert config.port == settings.port
    assert config.workers == 1
    assert config.access_log is False
    app.state.buzzer.db.close()


def test_listen_host_configurable(settings):
    # 與 SpecKit 組一致：監聽位址可用 BUZZER_HOST 設定（預設 127.0.0.1）
    changed = settings.model_copy(update={"host": "0.0.0.0"})
    app = create_app(changed)
    assert build_server_config(app, changed).host == "0.0.0.0"
    app.state.buzzer.db.close()
