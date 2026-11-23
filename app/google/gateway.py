"""Google 試算表存取層（design.md D3）。"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import requests
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession

from ..worksheet.grid import SpreadsheetGrid
from .auth import GoogleAuth
from .convert import grid_from_sheets_api
from .errors import SheetsError

logger = logging.getLogger("buzzer")

API_ROOT = "https://sheets.googleapis.com/v4/spreadsheets"
# 讀取儲存格的顯示值（formattedValue），與 SpecKit 組一致
FETCH_FIELDS = (
    "spreadsheetId,properties.title,"
    "sheets(properties(sheetId,title,index,sheetType),merges,"
    "data(startRow,startColumn,rowData(values(formattedValue))))"
)


@dataclass(frozen=True)
class CellWrite:
    sheet_title: str
    cell_ref: str
    text: str

    @property
    def a1_range(self) -> str:
        return "'" + self.sheet_title.replace("'", "''") + "'!" + self.cell_ref


class SheetsGateway(Protocol):
    def fetch(self, spreadsheet_id: str) -> SpreadsheetGrid: ...

    def write_cells(self, spreadsheet_id: str, writes: Sequence[CellWrite]) -> None: ...


def classify_response(response: Any, account: str | None = None) -> None:
    """非 2xx 回應轉成 SheetsError（不保留 Google 的原始內容）。

    401 → 授權失效、403 → 沒有權限、404 → 找不到，其他一律為暫時無法使用（與 SpecKit 組一致）。
    """
    status = int(response.status_code)
    if status < 400:
        return
    kind = {401: "auth_expired", 403: "forbidden", 404: "not_found"}.get(status, "unavailable")
    logger.info("Google API 請求失敗 status=%s kind=%s", status, kind)
    raise SheetsError(kind, status, account if kind == "forbidden" else None)  # type: ignore[arg-type]


class GoogleSheetsGateway:
    def __init__(self, auth: GoogleAuth, *, timeout_seconds: float = 10,
                 session_factory: Callable[[Any], Any] = AuthorizedSession) -> None:
        self._auth = auth
        self._timeout = timeout_seconds
        self._session_factory = session_factory

    def _call(self, method: str, url: str, **kwargs: Any) -> Any:
        session = self._session_factory(self._auth.credentials())
        try:
            response = session.request(method, url, timeout=self._timeout, **kwargs)
        except RefreshError:
            raise SheetsError("auth_expired") from None
        except (requests.exceptions.RequestException, TransportError, OSError):
            raise SheetsError("unavailable") from None
        classify_response(response, self._auth.account())
        try:
            return response.json()
        except ValueError:
            raise SheetsError("unavailable") from None

    def fetch(self, spreadsheet_id: str) -> SpreadsheetGrid:
        data = self._call("GET", f"{API_ROOT}/{quote(spreadsheet_id, safe='')}",
                          params={"includeGridData": "true", "fields": FETCH_FIELDS})
        return grid_from_sheets_api(data)

    def write_cells(self, spreadsheet_id: str, writes: Sequence[CellWrite]) -> None:
        if not writes:
            return
        body = {
            "valueInputOption": "RAW",  # 以文字原樣儲存，不解讀公式、數字或日期
            "data": [{"range": w.a1_range, "values": [[w.text]]} for w in writes],
        }
        self._call("POST", f"{API_ROOT}/{quote(spreadsheet_id, safe='')}/values:batchUpdate",
                   json=body)
