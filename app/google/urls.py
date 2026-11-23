"""Google 試算表網址解析（規則與 SpecKit 組一致）。

- 以 `https://docs.google.com/spreadsheets/d/` 開頭的網址：取其後到 `/`、`?`、`#` 之前的部分。
- 其他輸入：整段視為試算表 ID。
- 取出的 ID 必須是 20–100 個英數字、`_` 或 `-`；輸入長度上限 2048。
  「發布到網路」的連結（`/d/e/2PACX-…`）取出的是 `e`，因此會被拒絕。
"""

from __future__ import annotations

import re

_URL = re.compile(r"^https://docs\.google\.com/spreadsheets/d/([^/?#]+)")
_ID = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
MAX_LENGTH = 2048


def parse_spreadsheet_id(text: str | None) -> str | None:
    """從網址或純 ID 取出試算表 ID；無法辨識時回傳 None。"""
    value = (text or "").strip()
    match = _URL.match(value)
    candidate = match.group(1) if match else value
    if len(value) > MAX_LENGTH or not _ID.match(candidate):
        return None
    return candidate


def canonical_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
