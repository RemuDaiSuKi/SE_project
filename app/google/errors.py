"""Google 存取失敗的分類與繁中訊息（google-sheets-access spec）。"""

from __future__ import annotations

from typing import Literal

from fastapi import Request
from fastapi.responses import JSONResponse

from ..errors import error_response

SheetsErrorKind = Literal[
    "not_authorized", "auth_expired", "not_found", "forbidden", "api_disabled",
    "not_spreadsheet", "network", "unavailable",
]

LOGIN_HINT = "python -m app google-login"

MESSAGES: dict[str, tuple[int, str]] = {
    "not_authorized": (409, f"尚未完成 Google 授權，請先執行 {LOGIN_HINT}"),
    "auth_expired": (409, f"Google 授權已失效，請重新執行 {LOGIN_HINT}"),
    "not_found": (404, "找不到試算表，請確認網址是否正確"),
    "forbidden": (403, "目前授權的 Google 帳號沒有這份試算表的讀取或編輯權限，"
                       "請確認試算表已共用給該帳號"),
    "api_disabled": (502, "Google Cloud 專案尚未啟用 Google Sheets API，請依 README 啟用後再試"),
    "not_spreadsheet": (400, "這個檔案不是 Google 試算表格式，請先在 Google 試算表中選擇"
                             "「檔案 → 儲存為 Google 試算表」後再使用新檔案的網址"),
    "network": (502, "無法連線到 Google，請確認網路連線後再試"),
    "unavailable": (502, "Google 服務暫時無法使用，請稍後再試"),
}


class SheetsError(Exception):
    """Google 存取失敗。只保存分類與 HTTP 狀態碼，不保存 Google 的原始回應。"""

    def __init__(self, kind: SheetsErrorKind, status: int | None = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.status = status

    @property
    def message(self) -> str:
        return MESSAGES[self.kind][1]


async def sheets_error_handler(_: Request, exc: SheetsError) -> JSONResponse:
    status, message = MESSAGES[exc.kind]
    return error_response(status, f"GOOGLE_{exc.kind.upper()}", message)
