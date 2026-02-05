from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    id: str
    email: str


class WorkspaceOut(BaseModel):
    id: str
    name: str
    role: str


WorkspaceRole = Literal["admin", "member"]


class WorkspaceMemberOut(BaseModel):
    user_id: str
    email: str
    role: WorkspaceRole
    created_at: datetime


class WorkspaceMemberAddRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: WorkspaceRole = "member"

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        local, sep, domain = value.partition("@")
        if sep != "@" or not local or not domain:
            raise ValueError("Invalid email format.")
        if any(char.isspace() for char in value):
            raise ValueError("Invalid email format.")
        return value


class WorkspaceMemberRoleUpdateRequest(BaseModel):
    role: WorkspaceRole


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    default_workspace: WorkspaceOut | None


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class IngestResponse(BaseModel):
    documents: int
    chunks: int


ClassificationLabel = Literal["public", "internal", "confidential", "restricted"]


class DocumentInventoryItem(BaseModel):
    id: str
    title: str
    source_url: str | None
    license: str | None
    accessed_at: date | None
    classification_label: ClassificationLabel


class DocumentClassificationUpdateRequest(BaseModel):
    classification_label: ClassificationLabel


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class Citation(BaseModel):
    chunk_id: str
    source_title: str
    source_url: str | None
    score: float
    excerpt: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]


class AuditEvent(BaseModel):
    id: str
    workspace_id: str
    user_id: str | None
    action: str
    payload: dict[str, Any]
    created_at: datetime
