from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Iterable

from app.models import Chunk, Document

_HEADER_KEYS = {
    "titolo": "title",
    "fonte": "source_url",
    "licenza": "license",
    "accesso": "accessed_at",
}


def load_documents_from_dir(directory: Path, workspace_id: str) -> list[Document]:
    documents: list[Document] = []
    for path in sorted(directory.glob("*.txt")):
        documents.append(parse_wikipedia_file(path, workspace_id=workspace_id))
    return documents


def parse_wikipedia_file(path: Path, workspace_id: str | None = None) -> Document:
    raw = path.read_text(encoding="utf-8")
    header, body = _split_header_body(raw)
    metadata = _parse_header(header)

    title = metadata.get("title") or path.stem
    source_url = metadata.get("source_url")
    license_text = metadata.get("license")
    accessed_at = _parse_date(metadata.get("accessed_at"))

    text = body.strip()
    if not text:
        raise ValueError(f"Empty document body: {path}")

    return Document(
        workspace_id=workspace_id,
        title=title,
        source_url=source_url,
        license=license_text,
        accessed_at=accessed_at,
        text=text,
    )


def chunk_document(
    document: Document,
    *,
    chunk_size: int = 600,
    overlap: int = 120,
) -> list[Chunk]:
    if not document.workspace_id:
        raise ValueError("Document is missing workspace_id.")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")

    normalized = _normalize_text(document.text)
    chunks: list[Chunk] = []

    start = 0
    index = 0
    length = len(normalized)

    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            split_at = normalized.rfind(" ", start, end)
            if split_at > start + 50:
                end = split_at

        content = normalized[start:end].strip()
        if content:
            chunks.append(
                Chunk(
                    document_id=document.document_id,
                    workspace_id=document.workspace_id,
                    content=content,
                    start_char=start,
                    end_char=end,
                    chunk_index=index,
                    source_title=document.title,
                    source_url=document.source_url,
                )
            )
            index += 1

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def chunk_documents(documents: Iterable[Document]) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    for doc in documents:
        all_chunks.extend(chunk_document(doc))
    return all_chunks


def _split_header_body(raw: str) -> tuple[str, str]:
    parts = raw.split("\n\n", 1)
    if len(parts) == 1:
        return "", raw
    return parts[0], parts[1]


def _parse_header(header: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if not value:
            continue
        mapped = _HEADER_KEYS.get(key)
        if mapped:
            metadata[mapped] = value
    return metadata


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


# Debug helper for quick inspection during development.
# Not used in production; kept for learning clarity.

def document_debug_dict(document: Document) -> dict[str, str | None]:
    return {
        "workspace_id": document.workspace_id,
        "title": document.title,
        "source_url": document.source_url,
        "license": document.license,
        "accessed_at": document.accessed_at.isoformat() if document.accessed_at else None,
        "text_preview": document.text[:120],
    }
