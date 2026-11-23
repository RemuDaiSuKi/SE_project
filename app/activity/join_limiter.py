"""輸入組別代碼的輸錯限制（與 SpecKit 組一致，design.md D5）。

- 每個視窗（X-Window-Id）連續失敗達上限就鎖定一段時間；鎖定時計數歸零，成功一次也歸零。
- 全體最近 60 秒內的失敗達上限時，所有視窗都被拒絕，直到最早的那次失敗滿 60 秒。
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

from .errors import TooManyAttempts

GLOBAL_WINDOW_SECONDS = 60
MAX_TRACKED_WINDOWS = 10_000


@dataclass
class _WindowState:
    failures: int = 0
    locked_until: float = 0.0


class JoinLimiter:
    def __init__(self, max_failures: int, lock_seconds: int, global_max_failures: int,
                 clock=time.monotonic) -> None:
        self._max_failures = max_failures
        self._lock_seconds = lock_seconds
        self._global_limit = global_max_failures
        self._clock = clock
        self._windows: OrderedDict[str, _WindowState] = OrderedDict()
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    def check_allowed(self, window_id: str) -> None:
        """加入前呼叫：視窗被鎖定或全體失敗達上限時丟出 TooManyAttempts。"""
        with self._lock:
            now = self._clock()
            state = self._windows.get(window_id)
            if state is not None and now < state.locked_until:
                raise TooManyAttempts(math.ceil(state.locked_until - now))
            while self._global and now - self._global[0] >= GLOBAL_WINDOW_SECONDS:
                self._global.popleft()
            if len(self._global) >= self._global_limit:
                raise TooManyAttempts(math.ceil(GLOBAL_WINDOW_SECONDS - (now - self._global[0])))

    def record_failure(self, window_id: str) -> None:
        with self._lock:
            now = self._clock()
            self._global.append(now)
            state = self._windows.setdefault(window_id, _WindowState())
            self._windows.move_to_end(window_id)
            while len(self._windows) > MAX_TRACKED_WINDOWS:
                self._windows.popitem(last=False)
            state.failures += 1
            if state.failures >= self._max_failures:
                state.failures = 0
                state.locked_until = now + self._lock_seconds

    def record_success(self, window_id: str) -> None:
        with self._lock:
            self._windows.pop(window_id, None)
