from __future__ import annotations

from typing import Any
import logging
import uuid

from sqlalchemy import select

from app.config import store_backend
from app.db import SessionLocal
from app.sql_models import AuditLogORM

DEFAULT_AUDIT_LIMIT = 50
MAX_AUDIT_LIMIT = 200
SENSITIVE_KEYS = {
    "question",
    "prompt",
    "content",
    "text",
    "source_title",
    "source_url",
    "excerpt",
}

logger = logging.getLogger(__name__)


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
        logger.warning("audit_log skipped: invalid workspace_id=%s", workspace_id)
        return

    user_uuid = None
    if user_id:
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError as exc:
            logger.warning("audit_log skipped: invalid user_id=%s", user_id)
            return

    safe_payload = _sanitize_payload(payload)
    if "outcome" not in safe_payload:
        safe_payload["outcome"] = "success"

    try:
        with SessionLocal() as session:
            session.add(
                AuditLogORM(
                    workspace_id=workspace_uuid,
                    user_id=user_uuid,
                    action=action,
                    payload=safe_payload,
                )
            )
            session.commit()
    except Exception:
        logger.warning(
            "audit_log failed: action=%s workspace_id=%s user_id=%s",
            action,
            workspace_id,
            user_id,
            exc_info=True,
        )
        return


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


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if key in SENSITIVE_KEYS:
            sanitized[key] = "[redacted]"
        else:
            sanitized[key] = value
    return sanitized
