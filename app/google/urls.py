"""Google 試算表網址解析（design.md D5）。"""

from __future__ import annotations

import re

# 多帳號登入時網址會多一段 /u/<n>/
_PUBLISHED = re.compile(r"/spreadsheets/(?:u/\d+/)?d/e/")
_EDIT_URL = re.compile(r"/spreadsheets/(?:u/\d+/)?d/([A-Za-z0-9_-]+)")
_BARE_ID = re.compile(r"^[A-Za-z0-9_-]{20,}$")


def parse_spreadsheet_id(text: str | None) -> str | None:
    """從網址或純 ID 取出試算表 ID；無法辨識或為「發布到網路」的連結時回傳 None。"""
    value = (text or "").strip()
    if not value or _PUBLISHED.search(value):
        return None
    match = _EDIT_URL.search(value)
    if match:
        return match.group(1)
    if _BARE_ID.match(value):
        return value
    return None


def canonical_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
