from datetime import date
from pathlib import Path

from app.ingestion import chunk_document, parse_wikipedia_file
from app.models import Document


def test_parse_wikipedia_file(tmp_path: Path) -> None:
    sample = (
        "Titolo: Esempio\n"
        "Fonte: https://example.org\n"
        "Licenza: CC BY-SA 4.0\n"
        "Accesso: 2026-02-03\n"
        "\n"
        "Questo e' un testo di prova."
    )
    path = tmp_path / "doc.txt"
    path.write_text(sample, encoding="utf-8")

    doc = parse_wikipedia_file(path, workspace_id="workspace-1")
    assert doc.workspace_id == "workspace-1"
    assert doc.title == "Esempio"
    assert doc.source_url == "https://example.org"
    assert doc.license == "CC BY-SA 4.0"
    assert doc.accessed_at == date(2026, 2, 3)
    assert doc.text == "Questo e' un testo di prova."


def test_chunk_document_creates_chunks() -> None:
    doc_text = "Parola " * 200
    doc = Document(
        workspace_id="workspace-1",
        title="Documento",
        source_url=None,
        license=None,
        accessed_at=None,
        text=doc_text,
    )

    chunks = chunk_document(doc, chunk_size=120, overlap=20)
    assert len(chunks) >= 2
    assert all(chunk.content for chunk in chunks)
    assert chunks[0].chunk_index == 0


def test_parse_wikipedia_file_rejects_unsafe_source_url(tmp_path: Path) -> None:
    sample = (
        "Titolo: Esempio\n"
        "Fonte: javascript:alert(1)\n"
        "Licenza: CC BY-SA 4.0\n"
        "Accesso: 2026-02-03\n"
        "\n"
        "Questo e' un testo di prova."
    )
    path = tmp_path / "doc-malicious.txt"
    path.write_text(sample, encoding="utf-8")

    doc = parse_wikipedia_file(path, workspace_id="workspace-1")
    assert doc.source_url is None


def test_parse_wikipedia_file_redacts_pii_at_ingest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RAG_PII_INGEST_REDACTION_ENABLED", "1")
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "1")
    sample = (
        "Titolo: Esempio\n"
        "Fonte: https://example.org\n"
        "Licenza: CC BY-SA 4.0\n"
        "Accesso: 2026-02-03\n"
        "\n"
        "Contatta mario.rossi@example.com con CF RSSMRA85T10A562S."
    )
    path = tmp_path / "doc-pii.txt"
    path.write_text(sample, encoding="utf-8")

    doc = parse_wikipedia_file(path, workspace_id="workspace-1")

    assert "[REDACTED_EMAIL]" in doc.text
    assert "[REDACTED_TAX_ID]" in doc.text
    assert "mario.rossi@example.com" not in doc.text
    assert "RSSMRA85T10A562S" not in doc.text


def test_parse_wikipedia_file_keeps_pii_when_ingest_redaction_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("RAG_PII_INGEST_REDACTION_ENABLED", "0")
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "1")
    sample = (
        "Titolo: Esempio\n"
        "Fonte: https://example.org\n"
        "Licenza: CC BY-SA 4.0\n"
        "Accesso: 2026-02-03\n"
        "\n"
        "Contatta mario.rossi@example.com."
    )
    path = tmp_path / "doc-no-redact.txt"
    path.write_text(sample, encoding="utf-8")

    doc = parse_wikipedia_file(path, workspace_id="workspace-1")

    assert "mario.rossi@example.com" in doc.text
