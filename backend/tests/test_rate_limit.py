from __future__ import annotations

import numpy as np
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main as app_main
from app import rate_limit as rate_limit_module
from app.auth import UserContext
from app.models import Chunk
from app.rate_limit import InMemoryWindowRateLimiter, RateLimitDecision, RedisWindowRateLimiter
from app.retrieval import RetrievalResult
from app.schemas import LoginRequest, QueryRequest, RegisterRequest


class _FakeClock:
    def __init__(self) -> None:
        self._value = 1000.0

    def now(self) -> float:
        return self._value

    def advance(self, seconds: float) -> None:
        self._value += seconds


class _SingleResultStore:
    def has_workspace_data(self, workspace_id: str) -> bool:
        return True

    def search(
        self,
        query_embedding: np.ndarray,
        *,
        top_k: int,
        workspace_id: str | None,
        allowed_labels: set[str] | None = None,
    ) -> list[RetrievalResult]:
        content = f"workspace={workspace_id}"
        return [
            RetrievalResult(
                chunk=Chunk(
                    document_id="doc-1",
                    workspace_id=workspace_id,
                    content=content,
                    start_char=0,
                    end_char=len(content),
                    chunk_index=0,
                    source_title="Doc",
                    source_url=None,
                ),
                score=0.99,
            )
        ]


class _FakeRedisClient:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def register_script(self, _script: str):
        def _run(*, keys, args):
            key = keys[0]
            self._counts[key] = self._counts.get(key, 0) + 1
            return self._counts[key]

        return _run


class _CapturingLogger:
    def __init__(self) -> None:
        self.info_calls: list[tuple[str, dict]] = []
        self.warning_calls: list[tuple[str, dict]] = []

    def info(self, message: str, **kwargs) -> None:
        self.info_calls.append((message, kwargs))

    def warning(self, message: str, **kwargs) -> None:
        self.warning_calls.append((message, kwargs))


class _FakeScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeLoginSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, *_args, **_kwargs):
        return _FakeScalarResult(None)


class _FakeRegisterExistingSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, *_args, **_kwargs):
        return _FakeScalarResult(object())


def _request_with_client_ip(ip: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/login",
            "headers": [],
            "client": (ip, 54321),
        }
    )


def test_inmemory_rate_limiter_prunes_inactive_keys_on_cleanup() -> None:
    clock = _FakeClock()
    limiter = InMemoryWindowRateLimiter(now_fn=clock.now, cleanup_every_checks=1)

    limiter.check(key="workspace-a", limit=10, window_seconds=60)
    limiter.check(key="workspace-b", limit=10, window_seconds=60)
    assert set(limiter._events_by_key.keys()) == {"workspace-a", "workspace-b"}

    clock.advance(61)
    limiter.check(key="workspace-c", limit=10, window_seconds=60)

    assert set(limiter._events_by_key.keys()) == {"workspace-c"}
    assert len(limiter._events_by_key["workspace-c"]) == 1


def test_inmemory_rate_limiter_keeps_active_keys() -> None:
    clock = _FakeClock()
    limiter = InMemoryWindowRateLimiter(now_fn=clock.now, cleanup_every_checks=1)

    limiter.check(key="workspace-a", limit=10, window_seconds=60)
    clock.advance(30)
    limiter.check(key="workspace-a", limit=10, window_seconds=60)
    limiter.check(key="workspace-b", limit=10, window_seconds=60)

    assert set(limiter._events_by_key.keys()) == {"workspace-a", "workspace-b"}


def test_query_rate_limit_is_workspace_scoped(monkeypatch) -> None:
    events = []
    store = _SingleResultStore()
    clock = _FakeClock()

    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "0")
    monkeypatch.setattr(app_main, "chunk_store", store)
    monkeypatch.setattr(app_main, "query_rate_limiter", InMemoryWindowRateLimiter(now_fn=clock.now))
    monkeypatch.setattr(app_main, "embed_text", lambda _: np.array([1.0, 0.0]))
    monkeypatch.setattr(app_main, "llm_enabled", lambda: False)
    monkeypatch.setattr(app_main, "require_workspace_role", lambda *_args, **_kwargs: "member")
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: events.append(kwargs))

    user = UserContext(id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email="member@local")
    request = QueryRequest(question="test", top_k=1)
    workspace_a = "11111111-1111-1111-1111-111111111111"
    workspace_b = "22222222-2222-2222-2222-222222222222"

    first = app_main.query(workspace_a, request, user)
    second = app_main.query(workspace_b, request, user)

    assert first.answer == "workspace=11111111-1111-1111-1111-111111111111"
    assert second.answer == "workspace=22222222-2222-2222-2222-222222222222"
    assert len(events) == 2
    assert all(event["payload"]["outcome"] == "success" for event in events)
    assert first.policy.rate_limit_enabled is True
    assert first.policy.rate_limit_backend == "memory"
    assert first.policy.rate_limit_requests == 1
    assert first.policy.rate_limit_window_seconds == 60


def test_query_rate_limit_blocks_and_recovers_after_window(monkeypatch) -> None:
    events = []
    store = _SingleResultStore()
    clock = _FakeClock()

    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "0")
    monkeypatch.setattr(app_main, "chunk_store", store)
    monkeypatch.setattr(app_main, "query_rate_limiter", InMemoryWindowRateLimiter(now_fn=clock.now))
    monkeypatch.setattr(app_main, "embed_text", lambda _: np.array([1.0, 0.0]))
    monkeypatch.setattr(app_main, "llm_enabled", lambda: False)
    monkeypatch.setattr(app_main, "require_workspace_role", lambda *_args, **_kwargs: "member")
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: events.append(kwargs))

    user = UserContext(id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email="member@local")
    request = QueryRequest(question="test", top_k=1)
    workspace_id = "11111111-1111-1111-1111-111111111111"

    first = app_main.query(workspace_id, request, user)
    assert first.answer == "workspace=11111111-1111-1111-1111-111111111111"

    with pytest.raises(HTTPException) as exc_info:
        app_main.query(workspace_id, request, user)
    error = exc_info.value
    assert error.status_code == 429
    assert error.detail == "Too many requests. Please retry later."
    assert error.headers is not None
    assert int(error.headers["Retry-After"]) > 0

    failure_events = [event for event in events if event["payload"]["outcome"] == "failure"]
    assert len(failure_events) == 1
    assert failure_events[0]["payload"]["reason"] == "rate_limited"
    assert failure_events[0]["payload"]["rate_limit_enabled"] is True
    assert failure_events[0]["payload"]["rate_limit_backend"] == "memory"
    assert failure_events[0]["payload"]["rate_limit_requests"] == 1
    assert failure_events[0]["payload"]["rate_limit_window_seconds"] == 60

    clock.advance(61)
    third = app_main.query(workspace_id, request, user)
    assert third.answer == "workspace=11111111-1111-1111-1111-111111111111"


def test_query_rate_limit_uses_role_specific_limit(monkeypatch) -> None:
    events = []
    store = _SingleResultStore()
    clock = _FakeClock()

    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_REQUESTS", "20")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_REQUESTS_MEMBER", "2")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_REQUESTS_ADMIN", "5")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "0")
    monkeypatch.setattr(app_main, "chunk_store", store)
    monkeypatch.setattr(app_main, "query_rate_limiter", InMemoryWindowRateLimiter(now_fn=clock.now))
    monkeypatch.setattr(app_main, "embed_text", lambda _: np.array([1.0, 0.0]))
    monkeypatch.setattr(app_main, "llm_enabled", lambda: False)
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: events.append(kwargs))

    request = QueryRequest(question="test", top_k=1)
    workspace_member = "11111111-1111-1111-1111-111111111111"
    workspace_admin = "22222222-2222-2222-2222-222222222222"

    monkeypatch.setattr(app_main, "require_workspace_role", lambda *_args, **_kwargs: "member")
    member_user = UserContext(id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email="member@local")
    member_response = app_main.query(workspace_member, request, member_user)
    assert member_response.policy.rate_limit_requests == 2
    assert member_response.policy.rate_limit_remaining == 1

    monkeypatch.setattr(app_main, "require_workspace_role", lambda *_args, **_kwargs: "admin")
    admin_user = UserContext(id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", email="admin@local")
    admin_response = app_main.query(workspace_admin, request, admin_user)
    assert admin_response.policy.rate_limit_requests == 5
    assert admin_response.policy.rate_limit_remaining == 4


def test_ingest_rate_limit_uses_scope_specific_limits(monkeypatch) -> None:
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_REQUESTS", "8")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_REQUESTS_WORKSPACE", "4")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_REQUESTS_USER", "3")

    assert rate_limit_module.ingest_rate_limit_requests_for_scope("workspace") == 4
    assert rate_limit_module.ingest_rate_limit_requests_for_scope("user") == 3
    assert rate_limit_module.ingest_rate_limit_requests_for_scope("other") == 8


def test_query_rate_limit_logs_near_exhaustion(monkeypatch) -> None:
    store = _SingleResultStore()
    clock = _FakeClock()
    logger = _CapturingLogger()

    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "0")
    monkeypatch.setattr(app_main, "chunk_store", store)
    monkeypatch.setattr(app_main, "query_rate_limiter", InMemoryWindowRateLimiter(now_fn=clock.now))
    monkeypatch.setattr(app_main, "embed_text", lambda _: np.array([1.0, 0.0]))
    monkeypatch.setattr(app_main, "llm_enabled", lambda: False)
    monkeypatch.setattr(app_main, "require_workspace_role", lambda *_args, **_kwargs: "member")
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: None)
    monkeypatch.setattr(app_main, "logger", logger)

    user = UserContext(id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email="member@local")
    request = QueryRequest(question="test", top_k=1)
    workspace_id = "11111111-1111-1111-1111-111111111111"

    app_main.query(workspace_id, request, user)

    assert len(logger.info_calls) == 1
    message, payload = logger.info_calls[0]
    assert message == "query_rate_limit_near_exhaustion"
    assert payload["extra"]["workspace_id"] == workspace_id
    assert payload["extra"]["rate_limit_remaining"] == 1


def test_query_rate_limit_logs_denial_warning(monkeypatch) -> None:
    store = _SingleResultStore()
    clock = _FakeClock()
    logger = _CapturingLogger()

    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "0")
    monkeypatch.setattr(app_main, "chunk_store", store)
    monkeypatch.setattr(app_main, "query_rate_limiter", InMemoryWindowRateLimiter(now_fn=clock.now))
    monkeypatch.setattr(app_main, "embed_text", lambda _: np.array([1.0, 0.0]))
    monkeypatch.setattr(app_main, "llm_enabled", lambda: False)
    monkeypatch.setattr(app_main, "require_workspace_role", lambda *_args, **_kwargs: "member")
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: None)
    monkeypatch.setattr(app_main, "logger", logger)

    user = UserContext(id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email="member@local")
    request = QueryRequest(question="test", top_k=1)
    workspace_id = "11111111-1111-1111-1111-111111111111"

    app_main.query(workspace_id, request, user)
    with pytest.raises(HTTPException) as exc_info:
        app_main.query(workspace_id, request, user)

    assert exc_info.value.status_code == 429
    assert len(logger.warning_calls) == 1
    message, payload = logger.warning_calls[0]
    assert message == "query_rate_limit_denied"
    assert payload["extra"]["workspace_id"] == workspace_id
    assert payload["extra"]["access_role"] == "member"


def test_redis_window_rate_limiter_counts_per_window() -> None:
    clock = _FakeClock()
    limiter = RedisWindowRateLimiter(
        redis_client=_FakeRedisClient(),
        now_fn=clock.now,
    )

    first = limiter.check(key="workspace-1", limit=1, window_seconds=60)
    second = limiter.check(key="workspace-1", limit=1, window_seconds=60)

    assert first.allowed is True
    assert first.backend == "redis"
    assert first.remaining == 0
    assert second.allowed is False
    assert second.backend == "redis"
    assert second.retry_after_seconds > 0

    clock.advance(61)
    third = limiter.check(key="workspace-1", limit=1, window_seconds=60)
    assert third.allowed is True
    assert third.backend == "redis"


def test_resilient_rate_limit_falls_back_to_memory_once(monkeypatch) -> None:
    warnings = []

    class _FakeLogger:
        def warning(self, message: str, **kwargs) -> None:
            warnings.append((message, kwargs))

    class _FailingLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int):
            raise RuntimeError("redis unavailable")

    clock = _FakeClock()
    fallback = InMemoryWindowRateLimiter(now_fn=clock.now)
    monkeypatch.setenv("RAG_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(rate_limit_module, "logger", _FakeLogger())

    limiter = rate_limit_module.ResilientRateLimiter(
        primary=_FailingLimiter(),
        fallback=fallback,
    )

    first = limiter.check(key="workspace-1", limit=2, window_seconds=60)
    second = limiter.check(key="workspace-1", limit=2, window_seconds=60)

    assert first.allowed is True
    assert second.allowed is True
    assert len(warnings) == 1
    message, payload = warnings[0]
    assert message == "query_rate_limit_redis_unavailable_fallback_memory"
    assert payload["extra"]["redis_target"] == "redis://localhost:6379/0"
    assert payload["extra"]["error_type"] == "RuntimeError"
    assert payload["extra"]["consecutive_failures"] == 1
    assert payload["extra"]["fallback_backend"] == "memory"


def test_resilient_rate_limit_logs_periodically_on_persistent_failures(monkeypatch) -> None:
    warnings = []

    class _FakeLogger:
        def warning(self, message: str, **kwargs) -> None:
            warnings.append((message, kwargs))

    class _FailingLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int):
            raise RuntimeError("redis unavailable")

    clock = _FakeClock()
    fallback = InMemoryWindowRateLimiter(now_fn=clock.now)
    monkeypatch.setenv("RAG_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(rate_limit_module, "logger", _FakeLogger())

    limiter = rate_limit_module.ResilientRateLimiter(
        primary=_FailingLimiter(),
        fallback=fallback,
        relog_every_failures=3,
    )

    for _ in range(6):
        limiter.check(key="workspace-1", limit=100, window_seconds=60)

    assert len(warnings) == 3
    assert [entry[1]["extra"]["consecutive_failures"] for entry in warnings] == [1, 3, 6]


def test_build_query_rate_limiter_returns_resilient_wrapper(monkeypatch) -> None:
    class _FakeRedisLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int):
            return rate_limit_module.RateLimitDecision(
                allowed=True,
                backend="redis",
                limit=limit,
                window_seconds=window_seconds,
                remaining=limit - 1,
                retry_after_seconds=0,
            )

    monkeypatch.setattr(
        rate_limit_module,
        "RedisWindowRateLimiter",
        lambda **_kwargs: _FakeRedisLimiter(),
    )
    limiter = rate_limit_module.build_query_rate_limiter()

    decision = limiter.check(key="workspace-1", limit=3, window_seconds=60)
    assert decision.allowed is True
    assert decision.backend == "redis"


def test_build_query_rate_limiter_falls_back_when_redis_init_fails(monkeypatch) -> None:
    warnings = []

    class _FakeLogger:
        def warning(self, message: str, **kwargs) -> None:
            warnings.append((message, kwargs))

    def _boom(**_kwargs):
        raise RuntimeError("redis client init failed")

    monkeypatch.setattr(rate_limit_module, "RedisWindowRateLimiter", _boom)
    monkeypatch.setattr(rate_limit_module, "logger", _FakeLogger())
    monkeypatch.setenv("RAG_REDIS_URL", "redis://localhost:6379/0")

    limiter = rate_limit_module.build_query_rate_limiter()

    assert isinstance(limiter, InMemoryWindowRateLimiter)
    assert len(warnings) == 1
    message, payload = warnings[0]
    assert message == "query_rate_limit_redis_init_failed_fallback_memory"
    assert payload["extra"]["redis_target"] == "redis://localhost:6379/0"
    assert payload["extra"]["error_type"] == "RuntimeError"


def test_build_auth_login_rate_limiter_falls_back_when_redis_init_fails(monkeypatch) -> None:
    warnings = []

    class _FakeLogger:
        def warning(self, message: str, **kwargs) -> None:
            warnings.append((message, kwargs))

    def _boom(**_kwargs):
        raise RuntimeError("redis client init failed")

    monkeypatch.setattr(rate_limit_module, "RedisWindowRateLimiter", _boom)
    monkeypatch.setattr(rate_limit_module, "logger", _FakeLogger())
    monkeypatch.setenv("RAG_REDIS_URL", "redis://localhost:6379/0")

    limiter = rate_limit_module.build_auth_login_rate_limiter()

    assert isinstance(limiter, InMemoryWindowRateLimiter)
    assert len(warnings) == 1
    message, payload = warnings[0]
    assert message == "auth_login_rate_limit_redis_init_failed_fallback_memory"
    assert payload["extra"]["redis_target"] == "redis://localhost:6379/0"
    assert payload["extra"]["error_type"] == "RuntimeError"


def test_build_auth_register_rate_limiter_falls_back_when_redis_init_fails(monkeypatch) -> None:
    warnings = []

    class _FakeLogger:
        def warning(self, message: str, **kwargs) -> None:
            warnings.append((message, kwargs))

    def _boom(**_kwargs):
        raise RuntimeError("redis client init failed")

    monkeypatch.setattr(rate_limit_module, "RedisWindowRateLimiter", _boom)
    monkeypatch.setattr(rate_limit_module, "logger", _FakeLogger())
    monkeypatch.setenv("RAG_REDIS_URL", "redis://localhost:6379/0")

    limiter = rate_limit_module.build_auth_register_rate_limiter()

    assert isinstance(limiter, InMemoryWindowRateLimiter)
    assert len(warnings) == 1
    message, payload = warnings[0]
    assert message == "auth_register_rate_limit_redis_init_failed_fallback_memory"
    assert payload["extra"]["redis_target"] == "redis://localhost:6379/0"
    assert payload["extra"]["error_type"] == "RuntimeError"


def test_build_ingest_rate_limiter_falls_back_when_redis_init_fails(monkeypatch) -> None:
    warnings = []

    class _FakeLogger:
        def warning(self, message: str, **kwargs) -> None:
            warnings.append((message, kwargs))

    def _boom(**_kwargs):
        raise RuntimeError("redis client init failed")

    monkeypatch.setattr(rate_limit_module, "RedisWindowRateLimiter", _boom)
    monkeypatch.setattr(rate_limit_module, "logger", _FakeLogger())
    monkeypatch.setenv("RAG_REDIS_URL", "redis://localhost:6379/0")

    limiter = rate_limit_module.build_ingest_rate_limiter()

    assert isinstance(limiter, InMemoryWindowRateLimiter)
    assert len(warnings) == 1
    message, payload = warnings[0]
    assert message == "ingest_rate_limit_redis_init_failed_fallback_memory"
    assert payload["extra"]["redis_target"] == "redis://localhost:6379/0"
    assert payload["extra"]["error_type"] == "RuntimeError"


def test_auth_register_rate_limit_short_circuits_before_db_lookup(monkeypatch) -> None:
    class _AlwaysDenyLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
            return RateLimitDecision(
                allowed=False,
                backend="memory",
                limit=limit,
                window_seconds=window_seconds,
                remaining=0,
                retry_after_seconds=22,
            )

    logger = _CapturingLogger()

    def _fail_session_local():
        raise AssertionError(
            "SessionLocal should not be called when auth register is rate-limited"
        )

    monkeypatch.setenv("RAG_AUTH_REGISTER_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_AUTH_REGISTER_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RAG_AUTH_REGISTER_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(app_main, "auth_register_rate_limiter", _AlwaysDenyLimiter())
    monkeypatch.setattr(app_main, "logger", logger)
    monkeypatch.setattr(app_main, "SessionLocal", _fail_session_local)

    with pytest.raises(HTTPException) as exc_info:
        app_main.register(
            RegisterRequest(email="demo@local", password="secret-pass"),
            _request_with_client_ip("127.0.0.1"),
        )

    error = exc_info.value
    assert error.status_code == 429
    assert error.detail == "Too many registration attempts. Please retry later."
    assert error.headers is not None
    assert int(error.headers["Retry-After"]) > 0
    assert len(logger.warning_calls) == 1
    message, payload = logger.warning_calls[0]
    assert message == "auth_register_rate_limit_denied"
    assert payload["extra"]["rate_limit_scope"] == "ip"
    assert payload["extra"]["client_ip"] == "127.0.0.1"


def test_auth_register_rate_limit_logs_near_exhaustion(monkeypatch) -> None:
    class _NearExhaustionLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
            return RateLimitDecision(
                allowed=True,
                backend="memory",
                limit=limit,
                window_seconds=window_seconds,
                remaining=1,
                retry_after_seconds=0,
            )

    logger = _CapturingLogger()
    monkeypatch.setenv("RAG_AUTH_REGISTER_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_AUTH_REGISTER_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("RAG_AUTH_REGISTER_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(app_main, "auth_register_rate_limiter", _NearExhaustionLimiter())
    monkeypatch.setattr(app_main, "logger", logger)
    monkeypatch.setattr(app_main, "SessionLocal", lambda: _FakeRegisterExistingSession())

    with pytest.raises(HTTPException) as exc_info:
        app_main.register(
            RegisterRequest(email="demo@local", password="secret-pass"),
            _request_with_client_ip("127.0.0.1"),
        )

    assert exc_info.value.status_code == 400
    assert len(logger.info_calls) == 2
    assert logger.info_calls[0][0] == "auth_register_rate_limit_near_exhaustion"
    scopes = {entry[1]["extra"]["rate_limit_scope"] for entry in logger.info_calls}
    assert scopes == {"ip", "subject"}


def test_auth_login_rate_limit_short_circuits_before_db_lookup(monkeypatch) -> None:
    class _AlwaysDenyLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
            return RateLimitDecision(
                allowed=False,
                backend="memory",
                limit=limit,
                window_seconds=window_seconds,
                remaining=0,
                retry_after_seconds=20,
            )

    logger = _CapturingLogger()

    def _fail_session_local():
        raise AssertionError(
            "SessionLocal should not be called when auth login is rate-limited"
        )

    monkeypatch.setenv("RAG_AUTH_LOGIN_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_AUTH_LOGIN_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RAG_AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(app_main, "auth_login_rate_limiter", _AlwaysDenyLimiter())
    monkeypatch.setattr(app_main, "logger", logger)
    monkeypatch.setattr(app_main, "SessionLocal", _fail_session_local)

    with pytest.raises(HTTPException) as exc_info:
        app_main.login(
            LoginRequest(email="demo@local", password="wrong-pass"),
            _request_with_client_ip("127.0.0.1"),
        )

    error = exc_info.value
    assert error.status_code == 429
    assert error.detail == "Too many login attempts. Please retry later."
    assert error.headers is not None
    assert int(error.headers["Retry-After"]) > 0
    assert len(logger.warning_calls) == 1
    message, payload = logger.warning_calls[0]
    assert message == "auth_login_rate_limit_denied"
    assert payload["extra"]["rate_limit_scope"] == "ip"
    assert payload["extra"]["client_ip"] == "127.0.0.1"


def test_auth_login_rate_limit_logs_near_exhaustion(monkeypatch) -> None:
    class _NearExhaustionLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
            return RateLimitDecision(
                allowed=True,
                backend="memory",
                limit=limit,
                window_seconds=window_seconds,
                remaining=1,
                retry_after_seconds=0,
            )

    logger = _CapturingLogger()
    monkeypatch.setenv("RAG_AUTH_LOGIN_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_AUTH_LOGIN_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("RAG_AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(app_main, "auth_login_rate_limiter", _NearExhaustionLimiter())
    monkeypatch.setattr(app_main, "logger", logger)
    monkeypatch.setattr(app_main, "SessionLocal", lambda: _FakeLoginSession())

    with pytest.raises(HTTPException) as exc_info:
        app_main.login(
            LoginRequest(email="demo@local", password="wrong-pass"),
            _request_with_client_ip("127.0.0.1"),
        )

    assert exc_info.value.status_code == 401
    assert len(logger.info_calls) == 2
    assert logger.info_calls[0][0] == "auth_login_rate_limit_near_exhaustion"
    scopes = {entry[1]["extra"]["rate_limit_scope"] for entry in logger.info_calls}
    assert scopes == {"ip", "subject"}


def test_redis_target_redacts_credentials(monkeypatch) -> None:
    monkeypatch.setenv("RAG_REDIS_URL", "redis://user:secret@redis.internal:6380/2")
    assert rate_limit_module.redis_target() == "redis://redis.internal:6380/2"


def test_query_rate_limit_short_circuits_before_workspace_data_check(monkeypatch) -> None:
    class _NoDataStore:
        def has_workspace_data(self, workspace_id: str) -> bool:
            raise AssertionError("has_workspace_data should not be called when rate-limited")

    class _AlwaysDenyLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
            return RateLimitDecision(
                allowed=False,
                backend="memory",
                limit=limit,
                window_seconds=window_seconds,
                remaining=0,
                retry_after_seconds=30,
            )

    events = []
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(app_main, "chunk_store", _NoDataStore())
    monkeypatch.setattr(app_main, "query_rate_limiter", _AlwaysDenyLimiter())
    monkeypatch.setattr(app_main, "require_workspace_role", lambda *_args, **_kwargs: "member")
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: events.append(kwargs))

    user = UserContext(id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email="member@local")
    request = QueryRequest(question="test", top_k=1)
    workspace_id = "11111111-1111-1111-1111-111111111111"

    with pytest.raises(HTTPException) as exc_info:
        app_main.query(workspace_id, request, user)

    assert exc_info.value.status_code == 429
    assert events and events[0]["payload"]["reason"] == "rate_limited"
