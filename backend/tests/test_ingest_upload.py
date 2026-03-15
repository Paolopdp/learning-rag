from __future__ import annotations

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from app.models import Chunk, Document
from app.rate_limit import RateLimitDecision
from app.store import InMemoryChunkStore


@pytest.fixture(autouse=True)
def _isolated_chunk_store(monkeypatch) -> None:
    monkeypatch.setattr(app_main, "chunk_store", InMemoryChunkStore())


class _CapturingLogger:
    def __init__(self) -> None:
        self.info_calls: list[tuple[str, dict]] = []
        self.warning_calls: list[tuple[str, dict]] = []

    def info(self, message: str, **kwargs) -> None:
        self.info_calls.append((message, kwargs))

    def warning(self, message: str, **kwargs) -> None:
        self.warning_calls.append((message, kwargs))


def test_ingest_upload_accepts_text_and_markdown_files() -> None:
    client = TestClient(app)
    workspace_id = "11111111-1111-1111-1111-111111111111"

    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[
            ("files", ("guide.txt", b"Testo del documento uno.", "text/plain")),
            ("files", ("notes.md", b"# Titolo\n\nContenuto markdown.", "text/markdown")),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["documents"] == 2
    assert payload["chunks"] >= 2

    inventory = client.get(f"/workspaces/{workspace_id}/documents?limit=10&offset=0")
    assert inventory.status_code == 200
    titles = {item["title"] for item in inventory.json()}
    assert "guide" in titles
    assert "notes" in titles


def test_ingest_upload_rate_limit_short_circuits_before_workspace_check(monkeypatch) -> None:
    class _AlwaysDenyLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
            return RateLimitDecision(
                allowed=False,
                backend="memory",
                limit=limit,
                window_seconds=window_seconds,
                remaining=0,
                retry_after_seconds=25,
            )

    events = []
    logger = _CapturingLogger()

    def _fail_require_workspace_role(*_args, **_kwargs):
        raise AssertionError(
            "require_workspace_role should not run when upload request is rate-limited."
        )

    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(app_main, "ingest_rate_limiter", _AlwaysDenyLimiter())
    monkeypatch.setattr(app_main, "logger", logger)
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(app_main, "require_workspace_role", _fail_require_workspace_role)

    client = TestClient(app)
    workspace_id = "13131313-1313-1313-1313-131313131313"
    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[("files", ("doc.txt", b"abc", "text/plain"))],
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "Too many ingest requests. Please retry later."
    assert int(response.headers["Retry-After"]) > 0
    assert len(logger.warning_calls) == 1
    assert logger.warning_calls[0][0] == "ingest_rate_limit_denied"
    assert logger.warning_calls[0][1]["extra"]["rate_limit_scope"] == "user"

    upload_events = [event for event in events if event["action"] == "ingest_upload"]
    assert len(upload_events) == 1
    assert upload_events[0]["payload"]["outcome"] == "failure"
    assert upload_events[0]["payload"]["reason"] == "rate_limited"
    assert upload_events[0]["payload"]["rate_limit_scope"] == "user"


def test_ingest_upload_non_member_does_not_hit_workspace_scope_rate_limit(monkeypatch) -> None:
    checked_keys: list[str] = []

    class _AllowLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
            checked_keys.append(key)
            return RateLimitDecision(
                allowed=True,
                backend="memory",
                limit=limit,
                window_seconds=window_seconds,
                remaining=max(0, limit - 1),
                retry_after_seconds=0,
            )

    def _deny_membership(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="Workspace access denied.")

    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_REQUESTS_WORKSPACE", "10")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_REQUESTS_USER", "10")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(app_main, "ingest_rate_limiter", _AllowLimiter())
    monkeypatch.setattr(app_main, "require_workspace_role", _deny_membership)

    client = TestClient(app)
    workspace_id = "15151515-1515-1515-1515-151515151515"
    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[("files", ("doc.txt", b"abc", "text/plain"))],
    )

    assert response.status_code == 403
    assert checked_keys == ["ip:testclient"]


def test_ingest_upload_auth_disabled_uses_client_ip_for_user_scope(monkeypatch) -> None:
    checked_keys: list[str] = []

    class _AllowLimiter:
        def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
            checked_keys.append(key)
            return RateLimitDecision(
                allowed=True,
                backend="memory",
                limit=limit,
                window_seconds=window_seconds,
                remaining=max(0, limit - 1),
                retry_after_seconds=0,
            )

    monkeypatch.setenv("RAG_AUTH_DISABLED", "1")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_REQUESTS_WORKSPACE", "10")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_REQUESTS_USER", "10")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(app_main, "ingest_rate_limiter", _AllowLimiter())

    client = TestClient(app)
    workspace_id = "16161616-1616-1616-1616-161616161616"
    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[("files", ("doc.txt", b"abc", "text/plain"))],
    )

    assert response.status_code == 200
    assert checked_keys[0] == "ip:testclient"
    assert checked_keys[1] == f"workspace:{workspace_id}"


def test_ingest_upload_rate_limit_logs_near_exhaustion(monkeypatch) -> None:
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
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(app_main, "ingest_rate_limiter", _NearExhaustionLimiter())
    monkeypatch.setattr(app_main, "logger", logger)

    client = TestClient(app)
    workspace_id = "14141414-1414-1414-1414-141414141414"
    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[("files", ("doc.txt", b"abc", "text/plain"))],
    )

    assert response.status_code == 200
    assert len(logger.info_calls) == 2
    assert all(message == "ingest_rate_limit_near_exhaustion" for message, _ in logger.info_calls)
    scopes = {payload["extra"]["rate_limit_scope"] for _, payload in logger.info_calls}
    assert scopes == {"workspace", "user"}


def test_ingest_upload_replace_existing_clears_workspace_data() -> None:
    client = TestClient(app)
    workspace_id = "22222222-2222-2222-2222-222222222222"

    first = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[("files", ("first.txt", b"Primo documento.", "text/plain"))],
    )
    assert first.status_code == 200

    second = client.post(
        f"/workspaces/{workspace_id}/ingest?replace_existing=true",
        files=[("files", ("second.txt", b"Secondo documento.", "text/plain"))],
    )
    assert second.status_code == 200

    inventory = client.get(f"/workspaces/{workspace_id}/documents?limit=10&offset=0")
    assert inventory.status_code == 200
    payload = inventory.json()
    assert len(payload) == 1
    assert payload[0]["title"] == "second"


def test_ingest_upload_rejects_unsupported_files_and_logs_failure(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: events.append(kwargs))

    client = TestClient(app)
    workspace_id = "33333333-3333-3333-3333-333333333333"

    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[("files", ("payload.zip", b"binary", "application/zip"))],
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["message"] == "One or more uploaded files are invalid."
    assert len(detail["errors"]) == 1
    assert detail["errors"][0]["file_name"] == "payload.zip"
    assert "Unsupported file type" in detail["errors"][0]["error"]

    upload_events = [event for event in events if event["action"] == "ingest_upload"]
    assert len(upload_events) == 1
    assert upload_events[0]["payload"]["outcome"] == "failure"
    assert upload_events[0]["payload"]["reason"] == "invalid_files"
    assert upload_events[0]["payload"]["invalid_files_count"] == 1


def test_ingest_upload_skips_body_read_for_unsupported_suffix(monkeypatch) -> None:
    async def fail_read(_upload, _max_bytes):
        raise AssertionError("Body should not be read for unsupported file extension.")

    monkeypatch.setattr(app_main, "read_upload_with_limit", fail_read)

    client = TestClient(app)
    workspace_id = "39393939-3333-3333-3333-333333333333"
    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[("files", ("bad.zip", b"should-not-be-read", "application/zip"))],
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["message"] == "One or more uploaded files are invalid."
    assert detail["errors"][0]["file_name"] == "bad.zip"
    assert "Unsupported file type" in detail["errors"][0]["error"]


def test_ingest_upload_reports_blank_file_name_without_read(monkeypatch) -> None:
    async def fail_read(_upload, _max_bytes):
        raise AssertionError("Body should not be read when file name is blank.")

    monkeypatch.setattr(app_main, "read_upload_with_limit", fail_read)

    client = TestClient(app)
    workspace_id = "40404040-4444-4444-4444-444444444444"
    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[("files", ("   ", b"body", "text/plain"))],
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["message"] == "One or more uploaded files are invalid."
    assert detail["errors"][0]["file_name"] == "<unnamed>"
    assert "Missing file name" in detail["errors"][0]["error"]


def test_ingest_upload_logs_success_outcome(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: events.append(kwargs))

    client = TestClient(app)
    workspace_id = "44444444-4444-4444-4444-444444444444"

    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[("files", ("audit.txt", b"Documento audit.", "text/plain"))],
    )
    assert response.status_code == 200

    upload_events = [event for event in events if event["action"] == "ingest_upload"]
    assert len(upload_events) == 1
    payload = upload_events[0]["payload"]
    assert payload["outcome"] == "success"
    assert payload["documents"] == 1
    assert payload["files"] == 1


def test_ingest_upload_rejects_file_too_large(monkeypatch) -> None:
    monkeypatch.setenv("RAG_INGEST_MAX_FILE_BYTES", "8")
    client = TestClient(app)
    workspace_id = "55555555-5555-5555-5555-555555555555"

    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[("files", ("big.txt", b"123456789", "text/plain"))],
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["message"] == "One or more uploaded files are invalid."
    assert len(detail["errors"]) == 1
    assert detail["errors"][0]["file_name"] == "big.txt"
    assert "too large" in detail["errors"][0]["error"].lower()


def test_ingest_upload_aggregates_invalid_files_without_partial_write() -> None:
    client = TestClient(app)
    workspace_id = "88888888-8888-8888-8888-888888888888"

    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[
            ("files", ("good.txt", b"contenuto valido", "text/plain")),
            ("files", ("bad.zip", b"binary", "application/zip")),
            ("files", ("bad2.zip", b"binary", "application/zip")),
        ],
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["message"] == "One or more uploaded files are invalid."
    assert len(detail["errors"]) == 2
    invalid_names = {item["file_name"] for item in detail["errors"]}
    assert invalid_names == {"bad.zip", "bad2.zip"}

    inventory = client.get(f"/workspaces/{workspace_id}/documents?limit=10&offset=0")
    assert inventory.status_code == 200
    assert inventory.json() == []


def test_ingest_upload_rejects_too_many_files(monkeypatch) -> None:
    monkeypatch.setenv("RAG_INGEST_MAX_FILES", "1")
    client = TestClient(app)
    workspace_id = "66666666-6666-6666-6666-666666666666"

    response = client.post(
        f"/workspaces/{workspace_id}/ingest",
        files=[
            ("files", ("a.txt", b"a", "text/plain")),
            ("files", ("b.txt", b"b", "text/plain")),
        ],
    )

    assert response.status_code == 400
    assert "too many files" in response.json()["detail"].lower()


def test_ingest_upload_replace_existing_uses_store_atomic_write(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyStore:
        def clear_workspace(self, workspace_id: str) -> None:  # pragma: no cover - safety guard
            raise AssertionError("clear_workspace must not be called by endpoint.")

        def add_many(
            self,
            documents,
            chunks,
            embeddings,
            *,
            replace_existing=False,
            workspace_id=None,
        ) -> None:
            captured["replace_existing"] = replace_existing
            captured["workspace_id"] = workspace_id
            captured["documents"] = len(documents)
            captured["chunks"] = len(chunks)
            captured["embeddings"] = len(embeddings)

    def fake_parse_uploaded_file(*, filename: str, content: bytes, workspace_id: str):
        return Document(
            workspace_id=workspace_id,
            title=filename,
            source_url=None,
            license=None,
            accessed_at=None,
            text=content.decode("utf-8"),
        )

    def fake_chunk_documents(documents: list[Document]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for index, document in enumerate(documents):
            chunks.append(
                Chunk(
                    document_id=document.document_id,
                    workspace_id=document.workspace_id,
                    content=document.text,
                    start_char=0,
                    end_char=len(document.text),
                    chunk_index=index,
                    source_title=document.title,
                    source_url=document.source_url,
                )
            )
        return chunks

    monkeypatch.setattr(app_main, "chunk_store", DummyStore())
    monkeypatch.setattr(app_main, "parse_uploaded_file", fake_parse_uploaded_file)
    monkeypatch.setattr(app_main, "chunk_documents", fake_chunk_documents)
    monkeypatch.setattr(
        app_main,
        "embed_texts",
        lambda values: np.ones((len(values), 4), dtype=float),
    )

    client = TestClient(app)
    workspace_id = "77777777-7777-7777-7777-777777777777"
    response = client.post(
        f"/workspaces/{workspace_id}/ingest?replace_existing=true",
        files=[("files", ("atomic.txt", b"contenuto", "text/plain"))],
    )

    assert response.status_code == 200
    assert captured["replace_existing"] is True
    assert captured["workspace_id"] == workspace_id
    assert captured["documents"] == 1
