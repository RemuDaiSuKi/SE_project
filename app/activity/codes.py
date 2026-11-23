"""組別代碼的產生、正規化、格式檢查與雜湊（與 SpecKit 組一致）。"""

from __future__ import annotations

import hashlib
import secrets

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 32 個字，排除 0、1、I、O
LENGTH = 6


def new_code(existing: set[str]) -> str:
    """產生不在 existing 中的代碼（同一場活動內不重複）。"""
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
        if code not in existing:
            return code


def normalize(raw: str) -> str:
    """去掉所有空白字元並轉成大寫。"""
    return "".join(raw.split()).upper()


def is_well_formed(code: str) -> bool:
    return len(code) == LENGTH and all(c in ALPHABET for c in code)


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()
