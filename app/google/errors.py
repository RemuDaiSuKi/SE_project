"""Google 存取失敗的分類與繁中訊息（google-sheets-access spec）。"""

from __future__ import annotations

from typing import Literal

from fastapi import Request
from fastapi.responses import JSONResponse

from ..errors import error_response

SheetsErrorKind = Literal["not_authorized", "auth_expired", "not_found", "forbidden", "unavailable"]

LOGIN_HINT = "python -m app google-login"

# 分類與 SpecKit 組一致：401 授權失效、403 沒有權限、404 找不到，其他（含無法連線）一律為暫時無法使用
MESSAGES: dict[str, tuple[int, str]] = {
    "not_authorized": (409, f"尚未完成 Google 授權，請先執行 {LOGIN_HINT}"),
    "auth_expired": (409, f"Google 授權已失效，請重新執行 {LOGIN_HINT}"),
    "not_found": (404, "找不到試算表，請確認網址是否正確"),
    "forbidden": (403, "目前登入的 Google 帳號{account}沒有這份試算表的編輯權限，"
                       "請改用有權限的帳號重新登入，或請擁有者把試算表共用給這個帳號（編輯者）"),
    "unavailable": (502, "目前無法連線到 Google 試算表，請稍後再試"),
}


class SheetsError(Exception):
    """Google 存取失敗。只保存分類、HTTP 狀態碼與授權帳號，不保存 Google 的原始回應。"""

    def __init__(self, kind: SheetsErrorKind, status: int | None = None,
                 account: str | None = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.status = status
        self.account = account

    @property
    def message(self) -> str:
        account = f"（{self.account}）" if self.account else ""
        return MESSAGES[self.kind][1].format(account=account)


async def sheets_error_handler(_: Request, exc: SheetsError) -> JSONResponse:
    status, _message = MESSAGES[exc.kind]
    return error_response(status, f"GOOGLE_{exc.kind.upper()}", exc.message)
