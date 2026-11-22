from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.__main__ import build_server_config
from app.config import LISTEN_HOST, Settings, StartupError, invalid_setting_names
from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent


def test_defaults():
    s = Settings(_env_file=None)
    assert s.port == 8000
    assert s.max_upload_mb == 10 and s.max_uncompressed_mb == 100 and s.max_questions == 500
    assert (s.label_no, s.label_question, s.label_answer) == ("題號", "題目", "作答")
    assert s.lockout_max_failures == 5 and s.lockout_seconds == 60 and s.token_ttl_hours == 12
    assert s.teacher_password is None and not s.has_teacher_password()


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


def _run_main(env_updates: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("BUZZER_")}
    # PYTHONPATH 讓子程序能 import 專案的 app 套件；cwd 在暫存目錄，不會讀到專案的 .env
    env.update({"PYTHONIOENCODING": "utf-8", "BUZZER_DATA_DIR": str(tmp_path / "data"),
                "PYTHONPATH": str(ROOT)})
    env.update(env_updates)
    return subprocess.run([sys.executable, "-m", "app"], cwd=tmp_path, env=env,
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


def test_server_config_is_local_single_process(settings):
    app = create_app(settings)
    config = build_server_config(app, settings)
    assert config.host == LISTEN_HOST == "127.0.0.1"
    assert config.port == settings.port
    assert config.workers == 1
    assert config.access_log is False
    app.state.buzzer.db.close()
