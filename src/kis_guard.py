"""
KIS HTTP 호출용 간단 레이트리밋 + 서킷브레이커 (프로세스 내 상태).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, TypeVar

T = TypeVar("T")


class KISCallGuard:
    def __init__(
        self,
        *,
        max_per_minute: int = 60,
        fail_threshold: int = 5,
        cooldown_sec: int = 1800,
    ) -> None:
        self._max_per_minute = max(1, max_per_minute)
        self._fail_threshold = max(1, fail_threshold)
        self._cooldown_sec = max(1, cooldown_sec)
        self._lock = threading.Lock()
        self._ts: deque[float] = deque()
        self._consecutive_fail = 0
        self._open_until: float = 0.0

    def _prune(self, now: float) -> None:
        while self._ts and now - self._ts[0] > 60.0:
            self._ts.popleft()

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if now < self._open_until:
                return False
            self._prune(now)
            return len(self._ts) < self._max_per_minute

    def wait_slot(self, *, block_sec: float = 30.0) -> bool:
        deadline = time.monotonic() + block_sec
        while time.monotonic() < deadline:
            with self._lock:
                now = time.monotonic()
                if now < self._open_until:
                    time.sleep(min(1.0, self._open_until - now))
                    continue
                self._prune(now)
                if len(self._ts) < self._max_per_minute:
                    self._ts.append(now)
                    return True
            time.sleep(0.05)
        return False

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_fail = 0

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_fail += 1
            if self._consecutive_fail >= self._fail_threshold:
                self._open_until = time.monotonic() + float(self._cooldown_sec)
                self._consecutive_fail = 0

    def run(self, fn: Callable[[], T]) -> T:
        if not self.wait_slot():
            raise RuntimeError("KIS rate limit / circuit: 호출 슬롯 없음")
        try:
            out = fn()
        except Exception:
            self.record_failure()
            raise
        else:
            self.record_success()
        return out
