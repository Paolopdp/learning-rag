from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select

from app.config import store_backend
from app.db import SessionLocal
from app.sql_models import AuditLogORM

DEFAULT_AUDIT_LIMIT = 50
MAX_AUDIT_LIMIT = 200


def audit_enabled() -> bool:
    return store_backend() == "postgres"


def log_event(
    *,
    workspace_id: str,
    action: str,
    payload: dict[str, Any],
    user_id: str | None,
) -> None:
    if not audit_enabled():
        return

    try:
        workspace_uuid = uuid.UUID(workspace_id)
    except ValueError as exc:
        raise ValueError("Invalid workspace id.") from exc

    user_uuid = None
    if user_id:
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError as exc:
            raise ValueError("Invalid user id.") from exc

    with SessionLocal() as session:
        session.add(
            AuditLogORM(
                workspace_id=workspace_uuid,
                user_id=user_uuid,
                action=action,
                payload=payload,
            )
        )
        session.commit()


def list_events(workspace_id: str, *, limit: int = DEFAULT_AUDIT_LIMIT) -> list[AuditLogORM]:
    if not audit_enabled():
        return []

    try:
        workspace_uuid = uuid.UUID(workspace_id)
    except ValueError as exc:
        raise ValueError("Invalid workspace id.") from exc

    safe_limit = max(1, min(limit, MAX_AUDIT_LIMIT))
    with SessionLocal() as session:
        stmt = (
            select(AuditLogORM)
            .where(AuditLogORM.workspace_id == workspace_uuid)
            .order_by(AuditLogORM.created_at.desc())
            .limit(safe_limit)
        )
        return session.execute(stmt).scalars().all()
