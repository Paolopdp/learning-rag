from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select

from app.config import auth_disabled, jwt_algorithm, jwt_exp_minutes, jwt_secret
from app.db import SessionLocal
from app.rate_limit import (
    auth_token_rate_limit_enabled,
    auth_token_rate_limit_requests,
    auth_token_rate_limit_window_seconds,
    build_auth_token_rate_limiter,
)
from app.sql_models import UserORM, WorkspaceMemberORM

http_bearer = HTTPBearer(auto_error=False)
password_hasher = PasswordHasher()
logger = logging.getLogger(__name__)
auth_token_rate_limiter = build_auth_token_rate_limiter()
AUTH_TOKEN_RATE_LIMIT_NEAR_EXHAUSTION_MIN_REMAINING = 3
AUTH_TOKEN_RATE_LIMIT_NEAR_EXHAUSTION_RATIO = 0.2


@dataclass(frozen=True)
class UserContext:
    id: str
    email: str


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hasher.verify(hashed, password)
    except (InvalidHashError, VerificationError):
        return False


def create_access_token(user_id: str, email: str) -> str:
    expires_delta = timedelta(minutes=jwt_exp_minutes())
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.utcnow() + expires_delta,
    }
    return jwt.encode(payload, jwt_secret(), algorithm=jwt_algorithm())


def decode_token(token: str) -> dict[str, str]:
    try:
        return jwt.decode(token, jwt_secret(), algorithms=[jwt_algorithm()])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        ) from exc


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
) -> UserContext:
    if auth_disabled():
        return UserContext(id="00000000-0000-0000-0000-000000000000", email="demo@local")

    client_ip = request_client_ip(request)
    if credentials is None:
        enforce_auth_token_failure_rate_limit(
            client_ip=client_ip,
            failure_reason="missing_bearer_token",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    try:
        payload = decode_token(credentials.credentials)
    except HTTPException:
        enforce_auth_token_failure_rate_limit(
            client_ip=client_ip,
            failure_reason="invalid_token",
        )
        raise
    user_id = payload.get("sub")
    email = payload.get("email")
    if not user_id or not email:
        enforce_auth_token_failure_rate_limit(
            client_ip=client_ip,
            failure_reason="invalid_token_payload",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        )

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        enforce_auth_token_failure_rate_limit(
            client_ip=client_ip,
            failure_reason="invalid_token_payload",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        ) from exc

    with SessionLocal() as session:
        user = session.get(UserORM, user_uuid)
        if not user:
            enforce_auth_token_failure_rate_limit(
                client_ip=client_ip,
                failure_reason="token_user_not_found",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found.",
            )
    return UserContext(id=user_id, email=email)


def request_client_ip(request: Request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return request.client.host


def should_log_auth_token_rate_limit_near_exhaustion(*, remaining: int, limit: int) -> bool:
    threshold = max(
        1,
        min(
            AUTH_TOKEN_RATE_LIMIT_NEAR_EXHAUSTION_MIN_REMAINING,
            int(limit * AUTH_TOKEN_RATE_LIMIT_NEAR_EXHAUSTION_RATIO),
        ),
    )
    return remaining <= threshold


def enforce_auth_token_failure_rate_limit(*, client_ip: str, failure_reason: str) -> None:
    logger.warning(
        "auth_token_failure",
        extra={
            "client_ip": client_ip,
            "failure_reason": failure_reason,
        },
    )
    if not auth_token_rate_limit_enabled():
        return

    decision = auth_token_rate_limiter.check(
        key=f"ip:{client_ip}",
        limit=auth_token_rate_limit_requests(),
        window_seconds=auth_token_rate_limit_window_seconds(),
    )
    if not decision.allowed:
        logger.warning(
            "auth_token_rate_limit_denied",
            extra={
                "client_ip": client_ip,
                "failure_reason": failure_reason,
                "rate_limit_backend": decision.backend,
                "rate_limit_requests": decision.limit,
                "rate_limit_window_seconds": decision.window_seconds,
                "rate_limit_retry_after_seconds": decision.retry_after_seconds,
            },
        )
        raise HTTPException(
            status_code=429,
            detail="Too many authentication failures. Please retry later.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    if should_log_auth_token_rate_limit_near_exhaustion(
        remaining=decision.remaining,
        limit=decision.limit,
    ):
        logger.info(
            "auth_token_rate_limit_near_exhaustion",
            extra={
                "client_ip": client_ip,
                "failure_reason": failure_reason,
                "rate_limit_backend": decision.backend,
                "rate_limit_requests": decision.limit,
                "rate_limit_window_seconds": decision.window_seconds,
                "rate_limit_remaining": decision.remaining,
            },
        )


def require_workspace_role(
    workspace_id: str,
    user: UserContext,
    *,
    role: str | None = None,
) -> str:
    if auth_disabled():
        return "admin"

    try:
        workspace_uuid = uuid.UUID(workspace_id)
        user_uuid = uuid.UUID(user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid workspace or user id.",
        ) from exc

    with SessionLocal() as session:
        stmt = select(WorkspaceMemberORM).where(
            WorkspaceMemberORM.workspace_id == workspace_uuid,
            WorkspaceMemberORM.user_id == user_uuid,
        )
        membership = session.execute(stmt).scalar_one_or_none()
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace access denied.",
            )
        if role and membership.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role.",
            )
        return membership.role
