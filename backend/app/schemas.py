from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
