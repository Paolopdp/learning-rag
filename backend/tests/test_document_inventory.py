from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from app.auth import UserContext
from app.models import DocumentMetadata
from app.schemas import DocumentClassificationUpdateRequest


def test_document_inventory_lists_workspace_documents() -> None:
    client = TestClient(app)
    workspace_id = "11111111-1111-1111-1111-111111111111"

    ingest = client.post(f"/workspaces/{workspace_id}/ingest/demo")
    assert ingest.status_code == 200

    response = client.get(f"/workspaces/{workspace_id}/documents")
    assert response.status_code == 200
    payload = response.json()

    assert len(payload) > 0
    for document in payload:
        assert document["classification_label"] == "internal"
        assert document["id"]
        assert document["title"]


def test_document_classification_update_persists() -> None:
    client = TestClient(app)
    workspace_id = "11111111-1111-1111-1111-111111111111"

    ingest = client.post(f"/workspaces/{workspace_id}/ingest/demo")
    assert ingest.status_code == 200

    inventory = client.get(f"/workspaces/{workspace_id}/documents")
    document_id = inventory.json()[0]["id"]

    update = client.patch(
        f"/workspaces/{workspace_id}/documents/{document_id}/classification",
        json={"classification_label": "confidential"},
    )
    assert update.status_code == 200
    assert update.json()["classification_label"] == "confidential"

    refreshed = client.get(f"/workspaces/{workspace_id}/documents")
    refreshed_doc = next(
        item for item in refreshed.json() if item["id"] == document_id
    )
    assert refreshed_doc["classification_label"] == "confidential"


def test_document_classification_rejects_invalid_label() -> None:
    client = TestClient(app)
    workspace_id = "11111111-1111-1111-1111-111111111111"

    ingest = client.post(f"/workspaces/{workspace_id}/ingest/demo")
    assert ingest.status_code == 200

    inventory = client.get(f"/workspaces/{workspace_id}/documents")
    document_id = inventory.json()[0]["id"]

    update = client.patch(
        f"/workspaces/{workspace_id}/documents/{document_id}/classification",
        json={"classification_label": "top_secret"},
    )
    assert update.status_code == 422


def test_document_classification_rejects_invalid_document_id() -> None:
    client = TestClient(app)
    workspace_id = "11111111-1111-1111-1111-111111111111"

    ingest = client.post(f"/workspaces/{workspace_id}/ingest/demo")
    assert ingest.status_code == 200

    update = client.patch(
        f"/workspaces/{workspace_id}/documents/not-a-uuid/classification",
        json={"classification_label": "restricted"},
    )
    assert update.status_code == 400


def test_document_classification_is_workspace_scoped() -> None:
    client = TestClient(app)
    first_workspace = "11111111-1111-1111-1111-111111111111"
    second_workspace = "22222222-2222-2222-2222-222222222222"

    assert client.post(f"/workspaces/{first_workspace}/ingest/demo").status_code == 200
    assert client.post(f"/workspaces/{second_workspace}/ingest/demo").status_code == 200

    first_inventory = client.get(f"/workspaces/{first_workspace}/documents")
    first_document_id = first_inventory.json()[0]["id"]

    cross_update = client.patch(
        f"/workspaces/{second_workspace}/documents/{first_document_id}/classification",
        json={"classification_label": "restricted"},
    )
    assert cross_update.status_code == 404


def test_document_inventory_supports_limit_and_offset() -> None:
    client = TestClient(app)
    workspace_id = "11111111-1111-1111-1111-111111111111"

    ingest = client.post(f"/workspaces/{workspace_id}/ingest/demo")
    assert ingest.status_code == 200

    page_one = client.get(f"/workspaces/{workspace_id}/documents?limit=1&offset=0")
    page_two = client.get(f"/workspaces/{workspace_id}/documents?limit=1&offset=1")

    assert page_one.status_code == 200
    assert page_two.status_code == 200
    assert len(page_one.json()) == 1
    assert len(page_two.json()) == 1
    assert page_one.json()[0]["id"] != page_two.json()[0]["id"]


def test_document_inventory_logs_read_event(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: events.append(kwargs))

    client = TestClient(app)
    workspace_id = "11111111-1111-1111-1111-111111111111"

    ingest = client.post(f"/workspaces/{workspace_id}/ingest/demo")
    assert ingest.status_code == 200

    response = client.get(f"/workspaces/{workspace_id}/documents?limit=2&offset=1")
    assert response.status_code == 200

    read_events = [event for event in events if event["action"] == "document_inventory_read"]
    assert len(read_events) == 1
    payload = read_events[0]["payload"]
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert payload["outcome"] == "success"
    assert payload["returned"] == len(response.json())


def test_document_classification_logs_failure_outcome(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: events.append(kwargs))

    client = TestClient(app)
    workspace_id = "11111111-1111-1111-1111-111111111111"
    missing_document_id = "33333333-3333-3333-3333-333333333333"

    ingest = client.post(f"/workspaces/{workspace_id}/ingest/demo")
    assert ingest.status_code == 200

    response = client.patch(
        f"/workspaces/{workspace_id}/documents/{missing_document_id}/classification",
        json={"classification_label": "restricted"},
    )
    assert response.status_code == 404

    failure_events = [
        event for event in events if event["action"] == "document_classification_update"
    ]
    assert len(failure_events) > 0
    payload = failure_events[-1]["payload"]
    assert payload["document_id"] == missing_document_id
    assert payload["classification_label"] == "restricted"
    assert payload["outcome"] == "failure"
    assert payload["reason"] == "document_not_found"


def test_document_classification_requires_admin_role(monkeypatch) -> None:
    role_calls = []

    def fake_require_workspace_role(workspace_id, user, role=None):
        role_calls.append(role)
        return "admin"

    class DummyChunkStore:
        def update_document_classification(
            self,
            workspace_id: str,
            document_id: str,
            classification_label: str,
        ) -> DocumentMetadata:
            return DocumentMetadata(
                document_id=document_id,
                workspace_id=workspace_id,
                title="Doc",
                source_url=None,
                license=None,
                accessed_at=date(2026, 2, 5),
                classification_label=classification_label,
            )

    monkeypatch.setattr(app_main, "require_workspace_role", fake_require_workspace_role)
    monkeypatch.setattr(app_main, "log_event", lambda **kwargs: None)
    monkeypatch.setattr(app_main, "chunk_store", DummyChunkStore())

    workspace_id = "11111111-1111-1111-1111-111111111111"
    document_id = "22222222-2222-2222-2222-222222222222"
    current_user = UserContext(id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email="admin@local")

    result = app_main.update_document_classification(
        workspace_id=workspace_id,
        document_id=document_id,
        payload=DocumentClassificationUpdateRequest(classification_label="restricted"),
        current_user=current_user,
    )

    assert result.classification_label == "restricted"
    assert role_calls[-1] == "admin"
