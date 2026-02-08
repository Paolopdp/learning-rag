from __future__ import annotations

from app import store as store_module
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
