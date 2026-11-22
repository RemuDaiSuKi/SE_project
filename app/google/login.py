"""登入指令：python -m app google-login（design.md D4）。"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any, TextIO

from ..config import Settings, env_name
from .auth import SCOPES, save_token

USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def fetch_account_email(credentials: Any, timeout: float = 20) -> str | None:
    from google.auth.transport.requests import AuthorizedSession

    try:
        response = AuthorizedSession(credentials).get(USERINFO_URL, timeout=timeout)
        if response.status_code == 200:
            return response.json().get("email")
    except Exception:
        pass
    return None


def _default_flow_factory(path: str, scopes: list[str]) -> Any:
    from google_auth_oauthlib.flow import InstalledAppFlow

    return InstalledAppFlow.from_client_secrets_file(path, scopes=scopes)


def run_login(settings: Settings, *,
              flow_factory: Callable[[str, list[str]], Any] = _default_flow_factory,
              account_fetcher: Callable[[Any], str | None] = fetch_account_email,
              out: TextIO | None = None, err: TextIO | None = None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    client_path = settings.google_client_secrets_path
    if not client_path.is_file():
        print(f"找不到 Google OAuth 用戶端設定檔（{env_name('google_client_secrets')}）。\n"
              f"預期位置：{client_path}\n"
              "請依 README 在 Google Cloud 建立「桌面應用程式」類型的 OAuth 用戶端，"
              "下載 JSON 後放到上述位置，或以環境變數指定路徑。", file=err)
        return 1

    # Google 回傳的範圍順序可能與要求的不同，避免被誤判為範圍改變
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    print("即將開啟瀏覽器進行 Google 授權，請登入要讀寫學習單的 Google 帳號並同意授權。", file=out)
    try:
        flow = flow_factory(str(client_path), SCOPES)
        credentials = flow.run_local_server(
            host="localhost",
            bind_addr="127.0.0.1",  # 本機回呼只監聽 127.0.0.1
            port=0,
            open_browser=True,
            timeout_seconds=300,
            authorization_prompt_message="若瀏覽器沒有自動開啟，請手動前往：{url}",
            success_message="Google 授權完成，可以關閉這個視窗並回到終端機。",
        )
    except Exception:
        print("Google 授權未完成。", file=err)
        return 1
    if credentials is None or not getattr(credentials, "refresh_token", None):
        print("Google 授權未完成。", file=err)
        return 1

    account = account_fetcher(credentials)
    save_token(settings.google_token_path, credentials, account)
    print(f"已完成 Google 授權：{account or '（無法取得帳號 email）'}", file=out)
    return 0
