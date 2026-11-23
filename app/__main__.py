"""啟動入口：
- python -m app               啟動伺服器
- python -m app google-login  完成 Google 授權
"""

from __future__ import annotations

import sys

import uvicorn
from pydantic import ValidationError

from .config import (
    MISSING_PASSWORD_MESSAGE,
    Settings,
    StartupError,
    env_name,
    invalid_setting_names,
)
from .logging_setup import setup_logging

COMMANDS = ("google-login",)


def load_settings() -> Settings:
    return Settings()


def build_server_config(app, settings: Settings) -> uvicorn.Config:  # noqa: ANN001
    # 單一程序（記憶體狀態不可分散到多個 worker）、不輸出 access log
    return uvicorn.Config(app, host=settings.host, port=settings.port, workers=1,
                          access_log=False, server_header=False, log_level="info")


def google_startup_problem(settings: Settings) -> str | None:
    """缺少 OAuth 用戶端設定檔或尚未完成 Google 授權時，伺服器拒絕啟動（與 SpecKit 組一致）。"""
    from .google.auth import GoogleAuth, startup_problem
    from .google.errors import LOGIN_HINT

    status = GoogleAuth(settings.google_client_secrets_path, settings.google_token_path).status()
    return startup_problem(status, env_name("google_client_secrets"), LOGIN_HINT)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] not in COMMANDS:
        print(f"未知的指令：{args[0]}（可用指令：{'、'.join(COMMANDS)}）", file=sys.stderr)
        return 2
    setup_logging()
    try:
        settings = load_settings()
    except ValidationError as exc:
        print("設定不合法，無法執行：" + "、".join(invalid_setting_names(exc)), file=sys.stderr)
        return 1

    if args and args[0] == "google-login":
        from .google.login import run_login

        return run_login(settings)

    if not settings.has_teacher_password():
        print(MISSING_PASSWORD_MESSAGE, file=sys.stderr)
        return 1
    problem = google_startup_problem(settings)
    if problem:
        print(problem, file=sys.stderr)
        return 1

    try:
        from .main import create_app

        app = create_app(settings)
    except StartupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    uvicorn.Server(build_server_config(app, settings)).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
