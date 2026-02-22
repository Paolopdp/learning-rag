from __future__ import annotations

import math
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

_ENABLED_VALUES = {"1", "true", "yes"}
logger = logging.getLogger(__name__)


def query_rate_limit_enabled() -> bool:
    return os.getenv("RAG_QUERY_RATE_LIMIT_ENABLED", "1").lower() in _ENABLED_VALUES


def redis_url() -> str:
    return os.getenv("RAG_REDIS_URL", "redis://localhost:6379/0")


def redis_target() -> str:
    raw = redis_url()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return "redis://invalid"
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    db = parsed.path.lstrip("/") if parsed.path else "0"
    db_part = db if db else "0"
    scheme = parsed.scheme or "redis"
    return f"{scheme}://{host}:{port}/{db_part}"


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
    backend: str
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
                    backend="memory",
                    limit=limit,
                    window_seconds=window_seconds,
                    remaining=0,
                    retry_after_seconds=retry_after,
                )

            timestamps.append(now)
            remaining = max(0, limit - len(timestamps))
            return RateLimitDecision(
                allowed=True,
                backend="memory",
                limit=limit,
                window_seconds=window_seconds,
                remaining=remaining,
                retry_after_seconds=0,
            )

    def clear(self) -> None:
        with self._lock:
            self._events_by_key.clear()


class RedisWindowRateLimiter:
    _INCR_WITH_EXPIRE_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
end
return current
"""

    def __init__(
        self,
        *,
        redis_client=None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._now_fn = now_fn or time.time
        if redis_client is None:
            self._client = self._build_client()
        else:
            self._client = redis_client
        self._script = self._client.register_script(self._INCR_WITH_EXPIRE_SCRIPT)

    def check(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        now = self._now_fn()
        bucket_start = int(now // window_seconds) * window_seconds
        retry_after = max(1, int(math.ceil((bucket_start + window_seconds) - now)))
        redis_key = f"rag:query_rate_limit:{window_seconds}:{bucket_start}:{key}"

        count = int(
            self._script(
                keys=[redis_key],
                args=[window_seconds + 1],
            )
        )
        if count > limit:
            return RateLimitDecision(
                allowed=False,
                backend="redis",
                limit=limit,
                window_seconds=window_seconds,
                remaining=0,
                retry_after_seconds=retry_after,
            )

        return RateLimitDecision(
            allowed=True,
            backend="redis",
            limit=limit,
            window_seconds=window_seconds,
            remaining=max(0, limit - count),
            retry_after_seconds=0,
        )

    @staticmethod
    def _build_client():
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError(
                "redis package is not installed. Install backend dependencies."
            ) from exc
        return redis.Redis.from_url(
            redis_url(),
            socket_timeout=1.5,
            socket_connect_timeout=1.5,
            decode_responses=True,
        )


class ResilientRateLimiter:
    def __init__(self, *, primary, fallback) -> None:
        self._primary = primary
        self._fallback = fallback
        self._warning_emitted = False

    def check(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        try:
            return self._primary.check(
                key=key,
                limit=limit,
                window_seconds=window_seconds,
            )
        except Exception as exc:
            if not self._warning_emitted:
                self._warning_emitted = True
                logger.warning(
                    "query_rate_limit_redis_unavailable_fallback_memory",
                    extra={
                        "redis_target": redis_target(),
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "fallback_backend": "memory",
                    },
                )
            return self._fallback.check(
                key=key,
                limit=limit,
                window_seconds=window_seconds,
            )


def build_query_rate_limiter():
    fallback = InMemoryWindowRateLimiter()
    try:
        primary = RedisWindowRateLimiter()
    except Exception as exc:
        logger.warning(
            "query_rate_limit_redis_init_failed_fallback_memory",
            extra={
                "redis_target": redis_target(),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "fallback_backend": "memory",
            },
        )
        return fallback
    return ResilientRateLimiter(primary=primary, fallback=fallback)
