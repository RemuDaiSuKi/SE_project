"""啟動入口：
- python -m app               啟動伺服器
- python -m app google-login  完成 Google 授權
"""

from __future__ import annotations

import sys

import uvicorn
from pydantic import ValidationError

from .config import LISTEN_HOST, Settings, StartupError, invalid_setting_names
from .logging_setup import setup_logging

COMMANDS = ("google-login",)


def load_settings() -> Settings:
    return Settings()


def build_server_config(app, settings: Settings) -> uvicorn.Config:  # noqa: ANN001
    # 只監聽本機、單一程序（記憶體狀態不可分散到多個 worker）、不輸出 access log
    return uvicorn.Config(app, host=LISTEN_HOST, port=settings.port, workers=1,
                          access_log=False, server_header=False, log_level="info")


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
