from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_query_returns_citations_for_golden_queries() -> None:
    client = TestClient(app)
    workspace_id = "11111111-1111-1111-1111-111111111111"
    ingest = client.post(f"/workspaces/{workspace_id}/ingest/demo")
    assert ingest.status_code == 200

    cases = [
        (
            "Che cos’è SPID e a cosa serve?",
            ["SPID"],
        ),
        (
            "Qual è il ruolo di PagoPA?",
            ["PagoPA"],
        ),
        (
            "Cos’è l’ANPR e come si collega al Codice dell’Amministrazione Digitale?",
            ["Anagrafe nazionale della popolazione residente", "Codice dell'amministrazione digitale"],
        ),
    ]

    for question, expected_titles in cases:
        response = client.post(
            f"/workspaces/{workspace_id}/query",
            json={"question": question, "top_k": 3},
        )
        assert response.status_code == 200
        payload = response.json()

        assert payload["answer"]
        assert payload["citations"]
        assert payload["policy"]["policy_enforced"] is True
        assert payload["policy"]["policy_filtering_mode"] == "in_retrieval"
        assert payload["policy"]["access_role"] in {"admin", "member"}
        assert payload["policy"]["candidate_results"] >= payload["policy"]["returned_results"]
        titles = {c["source_title"] for c in payload["citations"]}
        assert any(expected in titles for expected in expected_titles)

    audit_response = client.get(f"/workspaces/{workspace_id}/audit")
    assert audit_response.status_code == 200
    audit_payload = audit_response.json()
    assert isinstance(audit_payload, list)
