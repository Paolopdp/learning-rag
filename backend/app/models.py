from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4


@dataclass(frozen=True)
class Document:
    workspace_id: str | None
    title: str
    source_url: str | None
    license: str | None
    accessed_at: date | None
    text: str
    classification_label: str = "internal"
    document_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class DocumentMetadata:
    document_id: str
    workspace_id: str | None
    title: str
    source_url: str | None
    license: str | None
    accessed_at: date | None
    classification_label: str


@dataclass(frozen=True)
class Chunk:
    document_id: str
    workspace_id: str | None
    content: str
    start_char: int
    end_char: int
    chunk_index: int
    source_title: str
    source_url: str | None
    chunk_id: str = field(default_factory=lambda: str(uuid4()))
