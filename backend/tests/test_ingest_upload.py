from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app


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
