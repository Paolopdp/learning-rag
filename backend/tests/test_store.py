from __future__ import annotations

import numpy as np

from app import store as store_module
from app.models import Chunk, Document
from app.store import PostgresChunkStore


def test_postgres_classification_map_ignores_invalid_document_ids(monkeypatch) -> None:
    class _FailIfCalledSessionLocal:
        def __call__(self):
            raise AssertionError("SessionLocal should not be called for invalid ids.")

    monkeypatch.setattr(store_module, "SessionLocal", _FailIfCalledSessionLocal())

    store = PostgresChunkStore()
    result = store.get_document_classification_map(
        workspace_id="11111111-1111-1111-1111-111111111111",
        document_ids=["not-a-uuid", "also-invalid"],
    )

    assert result == {}


def test_postgres_add_many_rejects_overlong_title_before_db_write(monkeypatch) -> None:
    class _FailIfCalledSessionLocal:
        def __call__(self):
            raise AssertionError("SessionLocal should not be called for invalid titles.")

    monkeypatch.setenv("RAG_DOCUMENT_TITLE_MAX_LENGTH", "8")
    monkeypatch.setattr(store_module, "SessionLocal", _FailIfCalledSessionLocal())

    document = Document(
        workspace_id="11111111-1111-1111-1111-111111111111",
        title="this_title_is_too_long",
        source_url=None,
        license=None,
        accessed_at=None,
        text="hello",
    )
    chunk = Chunk(
        document_id=document.document_id,
        workspace_id=document.workspace_id,
        content=document.text,
        start_char=0,
        end_char=5,
        chunk_index=0,
        source_title=document.title,
        source_url=None,
    )

    store = PostgresChunkStore()
    try:
        store.add_many([document], [chunk], np.array([[0.1, 0.2, 0.3]], dtype=float))
    except ValueError as exc:
        assert "max length" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for overlong title.")


def test_postgres_add_many_replace_existing_commits_once(monkeypatch) -> None:
    class _FakeSession:
        def __init__(self):
            self.commit_calls = 0
            self.flush_calls = 0

        def execute(self, _stmt):
            return None

        def add_all(self, _rows):
            return None

        def flush(self):
            self.flush_calls += 1

        def add(self, _row):
            return None

        def commit(self):
            self.commit_calls += 1

    class _FakeSessionLocal:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self

        def __enter__(self):
            return self._session

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_session = _FakeSession()
    monkeypatch.setattr(store_module, "SessionLocal", _FakeSessionLocal(fake_session))

    document = Document(
        workspace_id="11111111-1111-1111-1111-111111111111",
        title="doc",
        source_url=None,
        license=None,
        accessed_at=None,
        text="hello",
    )
    chunk = Chunk(
        document_id=document.document_id,
        workspace_id=document.workspace_id,
        content=document.text,
        start_char=0,
        end_char=5,
        chunk_index=0,
        source_title=document.title,
        source_url=None,
    )

    store = PostgresChunkStore()
    store.add_many(
        [document],
        [chunk],
        np.array([[0.1, 0.2, 0.3]], dtype=float),
        replace_existing=True,
        workspace_id=document.workspace_id,
    )

    assert fake_session.flush_calls == 1
    assert fake_session.commit_calls == 1
