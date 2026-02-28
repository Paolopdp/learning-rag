from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from app.models import Chunk, Document
from app.store import InMemoryChunkStore


@pytest.fixture(autouse=True)
def _isolated_chunk_store(monkeypatch) -> None:
    monkeypatch.setattr(app_main, "chunk_store", InMemoryChunkStore())


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
    assert "Unsupported file type" in response.json()["detail"]

    upload_events = [event for event in events if event["action"] == "ingest_upload"]
    assert len(upload_events) == 1
    assert upload_events[0]["payload"]["outcome"] == "failure"
    assert upload_events[0]["payload"]["reason"] == "invalid_file"


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
    assert "too large" in response.json()["detail"].lower()


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
