from __future__ import annotations

from types import SimpleNamespace
import uuid

import pytest

from app import audit


class _FakeScalarsResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalarsResult:
        return _FakeScalarsResult(self._rows)


class _FakeSession:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows
        self.statement = None

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, statement):
        self.statement = statement
        return _FakeExecuteResult(self._rows)


class _CaptureSession:
    def __init__(self) -> None:
        self.added = None

    def __enter__(self) -> _CaptureSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def add(self, row) -> None:
        self.added = row

    def commit(self) -> None:
        return None


def _enable_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "store_backend", lambda: "postgres")


def test_sanitize_payload_redacts_sensitive_keys() -> None:
    payload = {
        "question": "raw prompt",
        "content": "raw text",
        "top_k": 3,
        "results": 2,
    }

    redacted = audit._sanitize_payload(payload)

    assert redacted["question"] == "[redacted]"
    assert redacted["content"] == "[redacted]"
    assert redacted["top_k"] == 3
    assert redacted["results"] == 2


def test_log_event_skips_invalid_workspace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_audit(monkeypatch)
    state = {"called": False}

    class _NoDbSessionLocal:
        def __call__(self):
            state["called"] = True
            raise AssertionError("SessionLocal should not be called for invalid workspace id")

    monkeypatch.setattr(audit, "SessionLocal", _NoDbSessionLocal())

    audit.log_event(
        workspace_id="invalid-workspace-id",
        action="query",
        payload={"top_k": 3},
        user_id=None,
    )

    assert state["called"] is False


def test_log_event_adds_default_success_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_audit(monkeypatch)
    session = _CaptureSession()
    monkeypatch.setattr(audit, "SessionLocal", lambda: session)

    audit.log_event(
        workspace_id=str(uuid.uuid4()),
        action="query",
        payload={"top_k": 3},
        user_id=None,
    )

    assert session.added is not None
    assert session.added.payload["outcome"] == "success"
    assert session.added.payload["top_k"] == 3


def test_list_events_rejects_invalid_workspace_id_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_audit(monkeypatch)

    with pytest.raises(ValueError, match="Invalid workspace id."):
        audit.list_events("invalid-workspace-id")


def test_list_events_uses_workspace_filter_desc_order_and_clamped_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_audit(monkeypatch)
    rows = [SimpleNamespace(id=uuid.uuid4())]
    fake_session = _FakeSession(rows)
    monkeypatch.setattr(audit, "SessionLocal", lambda: fake_session)
    workspace_id = str(uuid.uuid4())

    events = audit.list_events(workspace_id, limit=999)

    assert events == rows
    assert fake_session.statement is not None
    sql = str(fake_session.statement)
    assert "WHERE audit_logs.workspace_id" in sql
    assert "ORDER BY audit_logs.created_at DESC" in sql

    compiled = fake_session.statement.compile()
    assert 200 in compiled.params.values()
