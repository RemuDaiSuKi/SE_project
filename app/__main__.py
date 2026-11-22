"""啟動入口：python -m app"""

from __future__ import annotations

import sys

import uvicorn
from pydantic import ValidationError

from .config import LISTEN_HOST, Settings, StartupError, invalid_setting_names
from .logging_setup import setup_logging


def load_settings() -> Settings:
    return Settings()


def build_server_config(app, settings: Settings) -> uvicorn.Config:  # noqa: ANN001
    # 只監聽本機、單一程序（記憶體狀態不可分散到多個 worker）、不輸出 access log
    return uvicorn.Config(app, host=LISTEN_HOST, port=settings.port, workers=1,
                          access_log=False, server_header=False, log_level="info")


def main() -> int:
    setup_logging()
    try:
        settings = load_settings()
    except ValidationError as exc:
        print("設定不合法，伺服器無法啟動：" + "、".join(invalid_setting_names(exc)),
              file=sys.stderr)
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
