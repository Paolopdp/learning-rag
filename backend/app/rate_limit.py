from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

_ENABLED_VALUES = {"1", "true", "yes"}


def query_rate_limit_enabled() -> bool:
    return os.getenv("RAG_QUERY_RATE_LIMIT_ENABLED", "1").lower() in _ENABLED_VALUES


def query_rate_limit_requests() -> int:
    return _positive_int_env("RAG_QUERY_RATE_LIMIT_REQUESTS", 20)


def query_rate_limit_window_seconds() -> int:
    return _positive_int_env("RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS", 60)


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    window_seconds: int
    remaining: int
    retry_after_seconds: int


class InMemoryWindowRateLimiter:
    def __init__(self, *, now_fn: Callable[[], float] | None = None) -> None:
        self._now_fn = now_fn or time.monotonic
        self._events_by_key: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        now = self._now_fn()
        cutoff = now - window_seconds

        with self._lock:
            timestamps = self._events_by_key.setdefault(key, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= limit:
                oldest = timestamps[0]
                retry_after = max(1, int(math.ceil(oldest + window_seconds - now)))
                return RateLimitDecision(
                    allowed=False,
                    limit=limit,
                    window_seconds=window_seconds,
                    remaining=0,
                    retry_after_seconds=retry_after,
                )

            timestamps.append(now)
            remaining = max(0, limit - len(timestamps))
            return RateLimitDecision(
                allowed=True,
                limit=limit,
                window_seconds=window_seconds,
                remaining=remaining,
                retry_after_seconds=0,
            )

    def clear(self) -> None:
        with self._lock:
            self._events_by_key.clear()
