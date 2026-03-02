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


def auth_login_rate_limit_enabled() -> bool:
    return os.getenv("RAG_AUTH_LOGIN_RATE_LIMIT_ENABLED", "1").lower() in _ENABLED_VALUES


def ingest_rate_limit_enabled() -> bool:
    return os.getenv("RAG_INGEST_RATE_LIMIT_ENABLED", "1").lower() in _ENABLED_VALUES


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


def query_rate_limit_requests_for_role(role: str) -> int:
    normalized = (role or "").strip().lower()
    if normalized == "admin":
        return _positive_int_env(
            "RAG_QUERY_RATE_LIMIT_REQUESTS_ADMIN",
            query_rate_limit_requests(),
        )
    if normalized == "member":
        return _positive_int_env(
            "RAG_QUERY_RATE_LIMIT_REQUESTS_MEMBER",
            query_rate_limit_requests(),
        )
    return query_rate_limit_requests()


def query_rate_limit_window_seconds() -> int:
    return _positive_int_env("RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS", 60)


def auth_login_rate_limit_requests() -> int:
    return _positive_int_env("RAG_AUTH_LOGIN_RATE_LIMIT_REQUESTS", 10)


def auth_login_rate_limit_window_seconds() -> int:
    return _positive_int_env("RAG_AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS", 60)


def ingest_rate_limit_requests() -> int:
    return _positive_int_env("RAG_INGEST_RATE_LIMIT_REQUESTS", 8)


def ingest_rate_limit_requests_for_scope(scope: str) -> int:
    normalized = (scope or "").strip().lower()
    if normalized == "workspace":
        return _positive_int_env(
            "RAG_INGEST_RATE_LIMIT_REQUESTS_WORKSPACE",
            ingest_rate_limit_requests(),
        )
    if normalized == "user":
        return _positive_int_env(
            "RAG_INGEST_RATE_LIMIT_REQUESTS_USER",
            ingest_rate_limit_requests(),
        )
    return ingest_rate_limit_requests()


def ingest_rate_limit_window_seconds() -> int:
    return _positive_int_env("RAG_INGEST_RATE_LIMIT_WINDOW_SECONDS", 60)


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
    def __init__(
        self,
        *,
        now_fn: Callable[[], float] | None = None,
        cleanup_every_checks: int = 256,
    ) -> None:
        self._now_fn = now_fn or time.monotonic
        self._events_by_key: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._cleanup_every_checks = max(1, cleanup_every_checks)
        self._checks = 0

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
            self._checks += 1
            if self._checks % self._cleanup_every_checks == 0:
                self._prune_stale_keys_locked(cutoff)

            timestamps = self._events_by_key.get(key)
            if timestamps is None:
                timestamps = deque()
                self._events_by_key[key] = timestamps
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if not timestamps:
                # Avoid retaining empty deques forever for inactive keys.
                self._events_by_key.pop(key, None)
                timestamps = deque()
                self._events_by_key[key] = timestamps

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
            self._checks = 0

    def _prune_stale_keys_locked(self, cutoff: float) -> None:
        stale_keys: list[str] = []
        for key, timestamps in self._events_by_key.items():
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if not timestamps:
                stale_keys.append(key)
        for stale_key in stale_keys:
            self._events_by_key.pop(stale_key, None)


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
        key_namespace: str = "query",
    ) -> None:
        self._now_fn = now_fn or time.time
        self._key_namespace = key_namespace
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
        redis_key = f"rag:{self._key_namespace}_rate_limit:{window_seconds}:{bucket_start}:{key}"

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
    def __init__(
        self,
        *,
        primary,
        fallback,
        relog_every_failures: int = 10,
        event_prefix: str = "query_rate_limit",
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._relog_every_failures = max(1, relog_every_failures)
        self._event_prefix = event_prefix
        self._consecutive_failures = 0
        self._last_error_type: str | None = None

    def check(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        try:
            decision = self._primary.check(
                key=key,
                limit=limit,
                window_seconds=window_seconds,
            )
            if self._consecutive_failures > 0:
                logger.info(
                    f"{self._event_prefix}_redis_recovered",
                    extra={
                        "redis_target": redis_target(),
                        "failed_attempts_before_recovery": self._consecutive_failures,
                    },
                )
            self._consecutive_failures = 0
            self._last_error_type = None
            return decision
        except Exception as exc:
            self._consecutive_failures += 1
            error_type = type(exc).__name__
            should_log = (
                self._consecutive_failures == 1
                or error_type != self._last_error_type
                or self._consecutive_failures % self._relog_every_failures == 0
            )
            if should_log:
                logger.warning(
                    f"{self._event_prefix}_redis_unavailable_fallback_memory",
                    extra={
                        "redis_target": redis_target(),
                        "error_type": error_type,
                        "consecutive_failures": self._consecutive_failures,
                        "fallback_backend": "memory",
                    },
                )
            self._last_error_type = error_type
            return self._fallback.check(
                key=key,
                limit=limit,
                window_seconds=window_seconds,
            )


def _build_rate_limiter(*, key_namespace: str, event_prefix: str):
    fallback = InMemoryWindowRateLimiter()
    try:
        primary = RedisWindowRateLimiter(key_namespace=key_namespace)
    except Exception as exc:
        logger.warning(
            f"{event_prefix}_redis_init_failed_fallback_memory",
            extra={
                "redis_target": redis_target(),
                "error_type": type(exc).__name__,
                "fallback_backend": "memory",
            },
        )
        return fallback
    return ResilientRateLimiter(
        primary=primary,
        fallback=fallback,
        event_prefix=event_prefix,
    )


def build_query_rate_limiter():
    return _build_rate_limiter(
        key_namespace="query",
        event_prefix="query_rate_limit",
    )


def build_auth_login_rate_limiter():
    return _build_rate_limiter(
        key_namespace="auth_login",
        event_prefix="auth_login_rate_limit",
    )


def build_ingest_rate_limiter():
    return _build_rate_limiter(
        key_namespace="ingest",
        event_prefix="ingest_rate_limit",
    )
