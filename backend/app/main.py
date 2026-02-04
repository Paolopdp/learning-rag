import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.audit import audit_enabled, list_events, log_event
from app.auth import UserContext, create_access_token, get_current_user, hash_password, require_workspace_role, verify_password
from app.config import auth_disabled, cors_origins, system_workspace_id, wikipedia_it_dir
from app.db import SessionLocal
from app.embeddings import embed_text, embed_texts
from app.ingestion import chunk_documents, load_documents_from_dir
from app.llm import generate_answer, llm_enabled
from app.observability import configure_otel
from app.schemas import (
    AuditEvent,
    AuthResponse,
    IngestResponse,
    LoginRequest,
    QueryRequest,
    QueryResponse,
    RegisterRequest,
    WorkspaceCreateRequest,
    WorkspaceOut,
)
from app.sql_models import UserORM, WorkspaceMemberORM, WorkspaceORM
from app.store import get_chunk_store

app = FastAPI(title="RAG Backend", version="0.1.0")

chunk_store = get_chunk_store()

configure_otel(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def require_workspace_uuid(workspace_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace id.") from exc


@app.post("/auth/register", response_model=AuthResponse)
def register(payload: RegisterRequest) -> AuthResponse:
    with SessionLocal() as session:
        existing = session.execute(
            select(UserORM).where(UserORM.email == payload.email)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered.")

        user = UserORM(
            email=payload.email,
            hashed_password=hash_password(payload.password),
        )
        workspace = WorkspaceORM(name="Default Workspace")
        session.add_all([user, workspace])
        session.flush()

        membership = WorkspaceMemberORM(
            user_id=user.id,
            workspace_id=workspace.id,
            role="admin",
        )
        session.add(membership)
        session.commit()

        if audit_enabled():
            domain = payload.email.split("@")[-1] if "@" in payload.email else "unknown"
            log_event(
                workspace_id=str(workspace.id),
                user_id=str(user.id),
                action="auth_register",
                payload={
                    "email_domain": domain,
                    "method": "password",
                },
            )

        token = create_access_token(str(user.id), user.email)
        return AuthResponse(
            access_token=token,
            user={"id": str(user.id), "email": user.email},
            default_workspace={
                "id": str(workspace.id),
                "name": workspace.name,
                "role": "admin",
            },
        )


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    with SessionLocal() as session:
        user = session.execute(
            select(UserORM).where(UserORM.email == payload.email)
        ).scalar_one_or_none()
        if not user or not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials.")

        workspace_row = session.execute(
            select(WorkspaceORM, WorkspaceMemberORM.role)
            .join(WorkspaceMemberORM, WorkspaceMemberORM.workspace_id == WorkspaceORM.id)
            .where(WorkspaceMemberORM.user_id == user.id)
            .limit(1)
        ).first()

        default_workspace = None
        if workspace_row:
            workspace, role = workspace_row
            default_workspace = {
                "id": str(workspace.id),
                "name": workspace.name,
                "role": role,
            }
            workspace_id = str(workspace.id)
        else:
            workspace_id = system_workspace_id()

        if audit_enabled():
            log_event(
                workspace_id=workspace_id,
                user_id=str(user.id),
                action="auth_login",
                payload={
                    "method": "password",
                },
            )

        token = create_access_token(str(user.id), user.email)
        return AuthResponse(
            access_token=token,
            user={"id": str(user.id), "email": user.email},
            default_workspace=default_workspace,
        )


@app.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(current_user: UserContext = Depends(get_current_user)) -> list[WorkspaceOut]:
    with SessionLocal() as session:
        rows = session.execute(
            select(WorkspaceORM, WorkspaceMemberORM.role)
            .join(WorkspaceMemberORM, WorkspaceMemberORM.workspace_id == WorkspaceORM.id)
            .where(WorkspaceMemberORM.user_id == uuid.UUID(current_user.id))
        ).all()
        return [
            WorkspaceOut(id=str(workspace.id), name=workspace.name, role=role)
            for workspace, role in rows
        ]


@app.post("/workspaces", response_model=WorkspaceOut)
def create_workspace(
    payload: WorkspaceCreateRequest,
    current_user: UserContext = Depends(get_current_user),
) -> WorkspaceOut:
    with SessionLocal() as session:
        workspace = WorkspaceORM(name=payload.name)
        session.add(workspace)
        session.flush()

        membership = WorkspaceMemberORM(
            user_id=uuid.UUID(current_user.id),
            workspace_id=workspace.id,
            role="admin",
        )
        session.add(membership)
        session.commit()

        return WorkspaceOut(id=str(workspace.id), name=workspace.name, role="admin")


@app.post("/workspaces/{workspace_id}/ingest/demo", response_model=IngestResponse)
def ingest_demo(
    workspace_id: str,
    current_user: UserContext = Depends(get_current_user),
) -> IngestResponse:
    require_workspace_uuid(workspace_id)
    require_workspace_role(workspace_id, current_user)

    documents = load_documents_from_dir(wikipedia_it_dir(), workspace_id=workspace_id)
    chunks = chunk_documents(documents)
    embeddings = embed_texts([chunk.content for chunk in chunks])
    chunk_store.clear_workspace(workspace_id)
    chunk_store.add_many(documents, chunks, embeddings)
    log_event(
        workspace_id=workspace_id,
        user_id=None if auth_disabled() else current_user.id,
        action="ingest_demo",
        payload={
            "documents": len(documents),
            "chunks": len(chunks),
            "source": "wikipedia_it",
        },
    )
    return IngestResponse(documents=len(documents), chunks=len(chunks))


@app.post("/workspaces/{workspace_id}/query", response_model=QueryResponse)
def query(
    workspace_id: str,
    request: QueryRequest,
    current_user: UserContext = Depends(get_current_user),
) -> QueryResponse:
    require_workspace_uuid(workspace_id)
    require_workspace_role(workspace_id, current_user)

    if not chunk_store.has_workspace_data(workspace_id):
        raise HTTPException(status_code=400, detail="No data ingested yet.")

    query_embedding = embed_text(request.question)
    results = chunk_store.search(
        query_embedding, top_k=request.top_k, workspace_id=workspace_id
    )

    if not results:
        return QueryResponse(answer="Nessun risultato.", citations=[])

    top_chunks = [result.chunk for result in results]
    if llm_enabled():
        try:
            answer = generate_answer(request.question, top_chunks)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        answer = top_chunks[0].content

    log_event(
        workspace_id=workspace_id,
        user_id=None if auth_disabled() else current_user.id,
        action="query",
        payload={
            "top_k": request.top_k,
            "results": len(results),
            "llm_used": llm_enabled(),
        },
    )

    citations = [
        {
            "chunk_id": result.chunk.chunk_id,
            "source_title": result.chunk.source_title,
            "source_url": result.chunk.source_url,
            "score": result.score,
            "excerpt": result.chunk.content[:200],
        }
        for result in results
    ]
    return QueryResponse(answer=answer, citations=citations)


@app.get("/workspaces/{workspace_id}/audit", response_model=list[AuditEvent])
def audit_log(
    workspace_id: str,
    limit: int = 50,
    current_user: UserContext = Depends(get_current_user),
) -> list[AuditEvent]:
    require_workspace_uuid(workspace_id)
    require_workspace_role(workspace_id, current_user)

    if not audit_enabled():
        return []

    try:
        events = list_events(workspace_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return [
        AuditEvent(
            id=str(event.id),
            workspace_id=str(event.workspace_id),
            user_id=str(event.user_id) if event.user_id else None,
            action=event.action,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in events
    ]
