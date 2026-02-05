from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


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
