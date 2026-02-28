from __future__ import annotations

from dataclasses import asdict
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from app.config import (
    document_title_max_length,
    ingest_max_pdf_pages,
    ingest_max_pdf_text_chars,
)
from app.models import Chunk, Document
from app.pii import pii_ingest_redaction_enabled, redact_text

_HEADER_KEYS = {
    "titolo": "title",
    "fonte": "source_url",
    "licenza": "license",
    "accesso": "accessed_at",
}
_ALLOWED_SOURCE_URL_SCHEMES = {"http", "https"}
_TEXT_UPLOAD_EXTENSIONS = {".txt", ".md", ".markdown"}
_PDF_UPLOAD_EXTENSION = ".pdf"
_UPLOAD_TYPE_ERROR = "Unsupported file type. Allowed: .txt, .md, .markdown, .pdf."


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
    source_url = _sanitize_source_url(metadata.get("source_url"))
    license_text = metadata.get("license")
    accessed_at = _parse_date(metadata.get("accessed_at"))

    return _build_document(
        title=title,
        source_url=source_url,
        license_text=license_text,
        accessed_at=accessed_at,
        raw_text=body,
        workspace_id=workspace_id,
    )


def parse_uploaded_file(
    *,
    filename: str,
    content: bytes,
    workspace_id: str | None = None,
) -> Document:
    suffix = validate_upload_filename(filename)
    if suffix in _TEXT_UPLOAD_EXTENSIONS:
        raw_text = _decode_uploaded_text(content)
    elif suffix == _PDF_UPLOAD_EXTENSION:
        raw_text = _extract_pdf_text(
            content,
            max_pages=ingest_max_pdf_pages(),
            max_text_chars=ingest_max_pdf_text_chars(),
        )
    else:
        raise ValueError(_UPLOAD_TYPE_ERROR)

    return _build_document(
        title=_derive_uploaded_title(filename),
        source_url=None,
        license_text=None,
        accessed_at=None,
        raw_text=raw_text,
        workspace_id=workspace_id,
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


def _sanitize_source_url(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in _ALLOWED_SOURCE_URL_SCHEMES:
        return None
    if not parsed.netloc:
        return None
    return candidate


def _build_document(
    *,
    title: str,
    source_url: str | None,
    license_text: str | None,
    accessed_at: date | None,
    raw_text: str,
    workspace_id: str | None,
) -> Document:
    clean_title = title.strip() or "uploaded_document"
    if len(clean_title) > document_title_max_length():
        raise ValueError(
            f"Document title is too long. Maximum length is {document_title_max_length()} characters."
        )

    text = raw_text.strip()
    if not text:
        raise ValueError("Empty document body.")
    text = redact_text(
        text,
        enabled=pii_ingest_redaction_enabled(),
    ).text

    return Document(
        workspace_id=workspace_id,
        title=clean_title,
        source_url=source_url,
        license=license_text,
        accessed_at=accessed_at,
        text=text,
    )


def _decode_uploaded_text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Uploaded text files must be UTF-8 encoded.") from exc


def _extract_pdf_text(
    content: bytes,
    *,
    max_pages: int,
    max_text_chars: int,
) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF support is not available on this server.") from exc

    try:
        reader = PdfReader(BytesIO(content))
    except Exception as exc:  # pragma: no cover - parser internals vary by file
        raise ValueError("Unable to parse PDF file.") from exc

    page_texts: list[str] = []
    extracted_chars = 0
    try:
        for index, page in enumerate(reader.pages):
            if index >= max_pages:
                raise ValueError(
                    f"PDF page limit exceeded. Maximum allowed pages is {max_pages}."
                )
            page_text = page.extract_text() or ""
            extracted_chars += len(page_text)
            if extracted_chars > max_text_chars:
                raise ValueError(
                    "PDF extracted text exceeds maximum allowed size "
                    f"({max_text_chars} characters)."
                )
            page_texts.append(page_text)
    except ValueError:
        raise
    except Exception as exc:  # pragma: no cover - parser internals vary by file
        raise ValueError("Unable to extract text from PDF file.") from exc

    merged = "\n".join(page_texts).strip()
    if not merged:
        raise ValueError("PDF does not contain extractable text.")
    return merged


def _derive_uploaded_title(filename: str) -> str:
    stem = Path(filename).stem.strip()
    if not stem:
        return "uploaded_document"
    return stem


def validate_upload_filename(filename: str) -> str:
    candidate = filename.strip()
    if not candidate:
        raise ValueError("Missing file name.")
    suffix = Path(candidate).suffix.lower()
    if suffix not in (_TEXT_UPLOAD_EXTENSIONS | {_PDF_UPLOAD_EXTENSION}):
        raise ValueError(_UPLOAD_TYPE_ERROR)
    return suffix


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
