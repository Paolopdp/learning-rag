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
