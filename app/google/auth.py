"""Google OAuth 授權資料的載入、自動更新與保存（design.md D4）。"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from .errors import SheetsError

logger = logging.getLogger("buzzer")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

CredentialsLoader = Callable[[dict[str, Any]], Any]


def _default_loader(info: dict[str, Any]) -> Credentials:
    return Credentials.from_authorized_user_info(info, SCOPES)


@dataclass(frozen=True)
class AuthStatus:
    configured: bool          # OAuth 用戶端設定檔存在
    authorized: bool          # 授權檔可載入且有更新權杖
    account: str | None


def startup_problem(status: AuthStatus, client_env: str, login_hint: str) -> str | None:
    """伺服器啟動前的 Google 檢查：缺少用戶端設定檔或尚未授權時回傳繁中說明。"""
    if not status.configured:
        return (f"找不到 Google OAuth 用戶端設定檔（{client_env}），伺服器無法啟動。"
                f"請依 README 設定後執行 {login_hint}")
    if not status.authorized:
        return f"尚未完成 Google 授權，伺服器無法啟動。請先執行 {login_hint}"
    return None


def save_token(path: Path, credentials: Any, account: str | None) -> None:
    """以原子性方式寫入授權檔（先寫暫存檔再取代）。"""
    data = {"account": account, "credentials": json.loads(credentials.to_json())}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


class GoogleAuth:
    """伺服器端的授權管理：快取憑證、過期自動更新並寫回授權檔。"""

    def __init__(self, client_secrets_path: Path, token_path: Path, *,
                 loader: CredentialsLoader = _default_loader,
                 request_factory: Callable[[], Any] = Request) -> None:
        self.client_secrets_path = Path(client_secrets_path)
        self.token_path = Path(token_path)
        self._loader = loader
        self._request_factory = request_factory
        self._lock = threading.Lock()
        self._credentials: Any = None
        self._account: str | None = None
        self._loaded_mtime: float | None = None

    def _load_locked(self) -> None:
        """授權檔不存在或損毀時清空快取；檔案被登入指令更新時重新載入。"""
        try:
            mtime = self.token_path.stat().st_mtime
        except OSError:
            self._credentials, self._account, self._loaded_mtime = None, None, None
            return
        if self._credentials is not None and mtime == self._loaded_mtime:
            return
        try:
            data = json.loads(self.token_path.read_text(encoding="utf-8"))
            self._credentials = self._loader(data["credentials"])
            self._account = data.get("account")
            self._loaded_mtime = mtime
        except Exception:  # 授權檔損毀：視為尚未授權
            logger.warning("Google 授權檔無法讀取，視為尚未授權")
            self._credentials, self._account, self._loaded_mtime = None, None, None

    def credentials(self) -> Any:
        """回傳有效的憑證；必要時自動更新並保存。"""
        with self._lock:
            self._load_locked()
            creds = self._credentials
            if creds is None:
                raise SheetsError("not_authorized")
            if creds.valid:
                return creds
            if not getattr(creds, "refresh_token", None):
                raise SheetsError("auth_expired")
            try:
                creds.refresh(self._request_factory())
            except RefreshError:
                logger.info("Google 授權更新失敗")
                raise SheetsError("auth_expired") from None
            except TransportError:
                raise SheetsError("unavailable") from None
            save_token(self.token_path, creds, self._account)
            self._loaded_mtime = self.token_path.stat().st_mtime
            logger.info("Google 存取權杖已自動更新")
            return creds

    def account(self) -> str | None:
        """目前授權的帳號 email（用於沒有權限的錯誤訊息）；尚未授權時為 None。"""
        with self._lock:
            self._load_locked()
            return self._account

    def status(self) -> AuthStatus:
        with self._lock:
            self._load_locked()
            creds = self._credentials
            authorized = creds is not None and bool(getattr(creds, "refresh_token", None))
            return AuthStatus(
                configured=self.client_secrets_path.is_file(),
                authorized=authorized,
                account=self._account if authorized else None,
            )
