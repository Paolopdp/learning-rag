from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import uuid

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select

from app.config import auth_disabled, jwt_algorithm, jwt_exp_minutes, jwt_secret
from app.db import SessionLocal
from app.sql_models import UserORM, WorkspaceMemberORM

http_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class UserContext:
    id: str
    email: str


def hash_password(password: str) -> str:
    # Pre-hash to avoid bcrypt 72-byte limit while keeping KISS.
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    hashed = bcrypt.hashpw(digest, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    try:
        return bcrypt.checkpw(digest, hashed.encode("utf-8"))
    except ValueError:
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
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
) -> UserContext:
    if auth_disabled():
        return UserContext(id="00000000-0000-0000-0000-000000000000", email="demo@local")

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    email = payload.get("email")
    if not user_id or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        )

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        ) from exc

    with SessionLocal() as session:
        user = session.get(UserORM, user_uuid)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found.",
            )
    return UserContext(id=user_id, email=email)


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
