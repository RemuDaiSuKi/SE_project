"""視窗身分、失敗鎖定與 Token。

所有狀態只在記憶體中，伺服器重啟後全部失效。
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Clock = Callable[[], float]

ROLE_TEACHER = "teacher"
MAX_WINDOWS = 10_000


@dataclass
class _WindowState:
    failures: int = 0
    locked_until: float = 0.0


class WindowRegistry:
    """伺服器發放的視窗識別，以及以視窗為單位的連續失敗鎖定。"""

    def __init__(self, max_failures: int, lock_seconds: int, clock: Clock = time.monotonic) -> None:
        self._max_failures = max_failures
        self._lock_seconds = lock_seconds
        self._clock = clock
        self._windows: OrderedDict[str, _WindowState] = OrderedDict()
        self._lock = threading.Lock()

    def register(self) -> str:
        window_id = secrets.token_urlsafe(16)  # 128 位元
        with self._lock:
            self._windows[window_id] = _WindowState()
            while len(self._windows) > MAX_WINDOWS:
                self._windows.popitem(last=False)
        return window_id

    def exists(self, window_id: str) -> bool:
        with self._lock:
            return window_id in self._windows

    def lock_remaining(self, window_id: str) -> int:
        """鎖定剩餘秒數（無條件進位）；未鎖定時為 0。"""
        with self._lock:
            state = self._windows.get(window_id)
            if state is None:
                return 0
            remaining = state.locked_until - self._clock()
            if remaining <= 0:
                if state.locked_until:
                    state.locked_until = 0.0
                    state.failures = 0
                return 0
            return max(1, math.ceil(remaining))

    def record_failure(self, window_id: str) -> None:
        with self._lock:
            state = self._windows.get(window_id)
            if state is None:
                return
            state.failures += 1
            if state.failures >= self._max_failures:
                state.locked_until = self._clock() + self._lock_seconds

    def record_success(self, window_id: str) -> None:
        with self._lock:
            state = self._windows.get(window_id)
            if state is not None:
                state.failures = 0
                state.locked_until = 0.0


@dataclass
class Session:
    role: str
    window_id: str
    expires_at: float
    attrs: dict[str, Any] = field(default_factory=dict)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionStore:
    """Token → 身分。只保存 Token 的 SHA-256。"""

    def __init__(self, ttl_seconds: int, clock: Clock = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def issue(self, role: str, window_id: str, **attrs: Any) -> str:
        token = secrets.token_urlsafe(32)
        session = Session(role=role, window_id=window_id,
                          expires_at=self._clock() + self._ttl, attrs=dict(attrs))
        with self._lock:
            self._sessions[_digest(token)] = session
        return token

    def resolve(self, token: str) -> Session | None:
        key = _digest(token)
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            if session.expires_at <= self._clock():
                del self._sessions[key]
                return None
            return session

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(_digest(token), None)

    def revoke_where(self, predicate: Callable[[Session], bool]) -> int:
        with self._lock:
            keys = [k for k, s in self._sessions.items() if predicate(s)]
            for key in keys:
                del self._sessions[key]
            return len(keys)


def password_matches(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()
