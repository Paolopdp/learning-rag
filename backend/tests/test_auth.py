import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from starlette.requests import Request

from app import auth as auth_module
from app.auth import get_current_user, hash_password, verify_password
from app.rate_limit import RateLimitDecision
from app.schemas import LoginRequest, RegisterRequest


def test_hash_and_verify_password() -> None:
    hashed = hash_password("secret-pass")
    assert hashed.startswith("$argon2id$")
    assert verify_password("secret-pass", hashed)
    assert not verify_password("wrong-pass", hashed)


def test_verify_password_returns_false_for_invalid_hash() -> None:
    assert verify_password("secret-pass", "not-a-valid-hash") is False


def test_register_request_normalizes_email() -> None:
    payload = RegisterRequest(email="  Demo@Local  ", password="secret-pass")
    assert payload.email == "demo@local"


def test_login_request_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="invalid-email", password="secret-pass")


class _CapturingLogger:
    def __init__(self) -> None:
        self.info_calls: list[tuple[str, dict]] = []
        self.warning_calls: list[tuple[str, dict]] = []

    def info(self, message: str, **kwargs) -> None:
        self.info_calls.append((message, kwargs))

    def warning(self, message: str, **kwargs) -> None:
        self.warning_calls.append((message, kwargs))


class _AlwaysAllowLimiter:
    def check(self, *, key: str, limit: int, window_seconds: int):
        return RateLimitDecision(
            allowed=True,
            backend="memory",
            limit=limit,
            window_seconds=window_seconds,
            remaining=limit - 1,
            retry_after_seconds=0,
        )


class _AlwaysDenyLimiter:
    def check(self, *, key: str, limit: int, window_seconds: int):
        return RateLimitDecision(
            allowed=False,
            backend="memory",
            limit=limit,
            window_seconds=window_seconds,
            remaining=0,
            retry_after_seconds=15,
        )


def _request_with_client_ip(ip: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/workspaces",
            "headers": [],
            "client": (ip, 54321),
        }
    )


def _request_without_client() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/workspaces",
            "headers": [],
        }
    )


def test_get_current_user_missing_bearer_returns_401_and_logs_failure(monkeypatch) -> None:
    logger = _CapturingLogger()
    monkeypatch.setattr(auth_module, "auth_disabled", lambda: False)
    monkeypatch.setenv("RAG_AUTH_TOKEN_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setattr(auth_module, "auth_token_rate_limiter", _AlwaysAllowLimiter())
    monkeypatch.setattr(auth_module, "logger", logger)

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request=_request_with_client_ip("127.0.0.1"), credentials=None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Missing bearer token."
    assert len(logger.warning_calls) == 1
    message, payload = logger.warning_calls[0]
    assert message == "auth_token_failure"
    assert payload["extra"]["failure_reason"] == "missing_bearer_token"


def test_get_current_user_missing_bearer_rate_limited_returns_429(monkeypatch) -> None:
    logger = _CapturingLogger()
    monkeypatch.setattr(auth_module, "auth_disabled", lambda: False)
    monkeypatch.setenv("RAG_AUTH_TOKEN_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setattr(auth_module, "auth_token_rate_limiter", _AlwaysDenyLimiter())
    monkeypatch.setattr(auth_module, "logger", logger)

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request=_request_with_client_ip("127.0.0.1"), credentials=None)

    error = exc_info.value
    assert error.status_code == 429
    assert error.detail == "Too many authentication failures. Please retry later."
    assert error.headers is not None
    assert int(error.headers["Retry-After"]) > 0
    assert len(logger.warning_calls) == 2
    assert logger.warning_calls[1][0] == "auth_token_rate_limit_denied"


def test_get_current_user_invalid_token_logs_near_exhaustion(monkeypatch) -> None:
    class _NearExhaustionLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int):
            return RateLimitDecision(
                allowed=True,
                backend="memory",
                limit=limit,
                window_seconds=window_seconds,
                remaining=1,
                retry_after_seconds=0,
            )

    logger = _CapturingLogger()
    monkeypatch.setattr(auth_module, "auth_disabled", lambda: False)
    monkeypatch.setenv("RAG_AUTH_TOKEN_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setattr(auth_module, "auth_token_rate_limiter", _NearExhaustionLimiter())
    monkeypatch.setattr(
        auth_module,
        "decode_token",
        lambda _token: (_ for _ in ()).throw(
            HTTPException(status_code=401, detail="Invalid token.")
        ),
    )
    monkeypatch.setattr(auth_module, "logger", logger)

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid")
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(
            request=_request_with_client_ip("127.0.0.1"),
            credentials=credentials,
        )

    assert exc_info.value.status_code == 401
    assert len(logger.warning_calls) == 1
    assert logger.warning_calls[0][0] == "auth_token_failure"
    assert logger.warning_calls[0][1]["extra"]["failure_reason"] == "invalid_token"
    assert len(logger.info_calls) == 1
    assert logger.info_calls[0][0] == "auth_token_rate_limit_near_exhaustion"


def test_request_client_ip_returns_none_when_missing_client() -> None:
    assert auth_module.request_client_ip(_request_without_client()) is None


def test_get_current_user_missing_client_skips_token_rate_limit_bucket(monkeypatch) -> None:
    checked_keys: list[str] = []
    logger = _CapturingLogger()

    class _CaptureLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int):
            checked_keys.append(key)
            return RateLimitDecision(
                allowed=True,
                backend="memory",
                limit=limit,
                window_seconds=window_seconds,
                remaining=limit - 1,
                retry_after_seconds=0,
            )

    monkeypatch.setattr(auth_module, "auth_disabled", lambda: False)
    monkeypatch.setenv("RAG_AUTH_TOKEN_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setattr(auth_module, "auth_token_rate_limiter", _CaptureLimiter())
    monkeypatch.setattr(auth_module, "logger", logger)

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request=_request_without_client(), credentials=None)

    assert exc_info.value.status_code == 401
    assert checked_keys == []
    assert len(logger.warning_calls) == 1
    assert logger.warning_calls[0][0] == "auth_token_failure"
    assert logger.warning_calls[0][1]["extra"]["client_ip"] is None
