from __future__ import annotations

import numpy as np

from app import main as app_main
from app.auth import UserContext
from app.models import Chunk
from app.retrieval import RetrievalResult
from app.schemas import QueryRequest


class _PolicyChunkStore:
    def __init__(
        self,
        *,
        results: list[RetrievalResult],
        classification_map: dict[str, str],
    ) -> None:
        self._results = results
        self._classification_map = classification_map
        self.last_top_k: int | None = None
        self.last_allowed_labels: set[str] | None = None

    def has_workspace_data(self, workspace_id: str) -> bool:
        return bool(self._results)

    def search(
        self,
        query_embedding: np.ndarray,
        *,
        top_k: int,
        workspace_id: str | None,
        allowed_labels: set[str] | None = None,
    ) -> list[RetrievalResult]:
        self.last_top_k = top_k
        self.last_allowed_labels = allowed_labels
        if allowed_labels is None:
            return self._results[:top_k]
        filtered = [
            result
            for result in self._results
            if self._classification_map.get(result.chunk.document_id) in allowed_labels
        ]
        return filtered[:top_k]

    def get_document_classification_map(
        self,
        workspace_id: str,
        document_ids: list[str],
    ) -> dict[str, str]:
        return {
            document_id: self._classification_map[document_id]
            for document_id in document_ids
            if document_id in self._classification_map
        }


def _result(
    *,
    document_id: str,
    title: str,
    content: str,
    score: float,
) -> RetrievalResult:
    return RetrievalResult(
        chunk=Chunk(
            document_id=document_id,
            workspace_id="11111111-1111-1111-1111-111111111111",
            content=content,
            start_char=0,
            end_char=len(content),
            chunk_index=0,
            source_title=title,
            source_url=None,
        ),
        score=score,
    )


def test_query_filters_restricted_chunks_for_member(monkeypatch) -> None:
    workspace_id = "11111111-1111-1111-1111-111111111111"
    events = []
    store = _PolicyChunkStore(
        results=[
            _result(
                document_id="doc-restricted",
                title="Restricted",
                content="restricted chunk",
                score=0.99,
            ),
            _result(
                document_id="doc-internal",
                title="Internal",
                content="internal chunk",
                score=0.90,
            ),
            _result(
                document_id="doc-public",
                title="Public",
                content="public chunk",
                score=0.80,
            ),
        ],
        classification_map={
            "doc-restricted": "restricted",
            "doc-internal": "internal",
            "doc-public": "public",
        },
    )

    monkeypatch.setattr(app_main, "chunk_store", store)
    monkeypatch.setattr(app_main, "embed_text", lambda _: np.array([1.0, 0.0]))
    monkeypatch.setattr(app_main, "llm_enabled", lambda: False)
    monkeypatch.setattr(app_main, "require_workspace_role", lambda *_args, **_kwargs: "member")
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: events.append(kwargs))

    response = app_main.query(
        workspace_id=workspace_id,
        request=QueryRequest(question="test", top_k=2),
        current_user=UserContext(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            email="member@local",
        ),
    )

    assert response.answer == "internal chunk"
    assert len(response.citations) == 2
    assert {citation.source_title for citation in response.citations} == {"Internal", "Public"}
    assert response.policy.access_role == "member"
    assert response.policy.allowed_classification_labels == ["internal", "public"]
    assert response.policy.policy_filtering_mode == "in_retrieval"
    assert response.policy.candidate_results == 2
    assert response.policy.returned_results == 2
    assert store.last_top_k == 2
    assert store.last_allowed_labels == {"internal", "public"}

    assert len(events) == 1
    assert events[0]["action"] == "query"
    payload = events[0]["payload"]
    assert payload["results"] == 2
    assert payload["candidate_results"] == 2
    assert payload["access_role"] == "member"
    assert payload["allowed_classification_labels"] == ["internal", "public"]
    assert payload["policy_filtering_mode"] == "in_retrieval"
    assert payload["outcome"] == "success"


def test_query_returns_empty_when_policy_blocks_all_results(monkeypatch) -> None:
    workspace_id = "11111111-1111-1111-1111-111111111111"
    events = []
    store = _PolicyChunkStore(
        results=[
            _result(
                document_id="doc-restricted",
                title="Restricted",
                content="restricted chunk",
                score=0.99,
            ),
        ],
        classification_map={
            "doc-restricted": "restricted",
        },
    )

    monkeypatch.setattr(app_main, "chunk_store", store)
    monkeypatch.setattr(app_main, "embed_text", lambda _: np.array([1.0, 0.0]))
    monkeypatch.setattr(app_main, "llm_enabled", lambda: False)
    monkeypatch.setattr(app_main, "require_workspace_role", lambda *_args, **_kwargs: "member")
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: events.append(kwargs))

    response = app_main.query(
        workspace_id=workspace_id,
        request=QueryRequest(question="test", top_k=3),
        current_user=UserContext(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            email="member@local",
        ),
    )

    assert response.answer == "Nessun risultato."
    assert response.citations == []
    assert response.policy.access_role == "member"
    assert response.policy.allowed_classification_labels == ["internal", "public"]
    assert response.policy.policy_filtering_mode == "in_retrieval"
    assert response.policy.candidate_results == 0
    assert response.policy.returned_results == 0

    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["results"] == 0
    assert payload["candidate_results"] == 0
    assert payload["policy_filtering_mode"] == "in_retrieval"
    assert payload["llm_used"] is False
    assert payload["outcome"] == "success"


def test_unknown_role_logs_structured_warning(monkeypatch) -> None:
    warnings = []

    class _FakeLogger:
        def warning(self, message: str, **kwargs) -> None:
            warnings.append((message, kwargs))

    monkeypatch.setattr(app_main, "logger", _FakeLogger())
    labels = app_main.allowed_labels_for_role("viewer")

    assert labels == {"public"}
    assert len(warnings) == 1
    message, payload = warnings[0]
    assert message == "query_policy_unknown_workspace_role"
    assert payload["extra"]["role"] == "viewer"
