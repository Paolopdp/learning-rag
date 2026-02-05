import logging
import uuid

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

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
    DocumentClassificationUpdateRequest,
    DocumentInventoryItem,
    IngestResponse,
    LoginRequest,
    QueryRequest,
    QueryResponse,
    RegisterRequest,
    WorkspaceCreateRequest,
    WorkspaceMemberAddRequest,
    WorkspaceMemberOut,
    WorkspaceMemberRoleUpdateRequest,
    WorkspaceOut,
)
from app.sql_models import UserORM, WorkspaceMemberORM, WorkspaceORM
from app.store import get_chunk_store

app = FastAPI(title="RAG Backend", version="0.1.0")
logger = logging.getLogger(__name__)

chunk_store = get_chunk_store()

DEFAULT_DOCUMENTS_LIMIT = 50
MAX_DOCUMENTS_LIMIT = 200

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


def require_document_uuid(document_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document id.") from exc


def require_user_uuid(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid user id.") from exc


def to_document_inventory_item(document) -> DocumentInventoryItem:
    return DocumentInventoryItem(
        id=document.document_id,
        title=document.title,
        source_url=document.source_url,
        license=document.license,
        accessed_at=document.accessed_at,
        classification_label=document.classification_label,
    )


def count_workspace_admins(session, workspace_uuid: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(WorkspaceMemberORM)
        .where(
            WorkspaceMemberORM.workspace_id == workspace_uuid,
            WorkspaceMemberORM.role == "admin",
        )
    )
    return int(session.execute(stmt).scalar_one())


def to_workspace_member_out(member: WorkspaceMemberORM, user: UserORM) -> WorkspaceMemberOut:
    return WorkspaceMemberOut(
        user_id=str(member.user_id),
        email=user.email,
        role=member.role,
        created_at=member.created_at,
    )


def require_workspace_exists(session, workspace_uuid: uuid.UUID) -> None:
    workspace = session.get(WorkspaceORM, workspace_uuid)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")


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


@app.get("/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberOut])
def list_workspace_members(
    workspace_id: str,
    current_user: UserContext = Depends(get_current_user),
) -> list[WorkspaceMemberOut]:
    workspace_uuid = require_workspace_uuid(workspace_id)
    require_workspace_role(workspace_id, current_user)

    with SessionLocal() as session:
        require_workspace_exists(session, workspace_uuid)
        rows = session.execute(
            select(WorkspaceMemberORM, UserORM)
            .outerjoin(UserORM, UserORM.id == WorkspaceMemberORM.user_id)
            .where(WorkspaceMemberORM.workspace_id == workspace_uuid)
            .order_by(WorkspaceMemberORM.created_at.asc())
        ).all()

        output: list[WorkspaceMemberOut] = []
        for membership, user in rows:
            if user is None:
                missing_user_id = str(membership.user_id)
                log_event(
                    workspace_id=workspace_id,
                    user_id=None if auth_disabled() else current_user.id,
                    action="workspace_member_read",
                    payload={
                        "outcome": "failure",
                        "reason": "missing_user_record",
                        "missing_user_id": missing_user_id,
                        "returned_before_error": len(output),
                    },
                )
                logger.warning(
                    "Workspace membership integrity error: workspace_id=%s missing_user_id=%s",
                    workspace_id,
                    missing_user_id,
                )
                raise HTTPException(
                    status_code=500,
                    detail="Workspace membership data integrity error.",
                )
            output.append(to_workspace_member_out(membership, user))
    log_event(
        workspace_id=workspace_id,
        user_id=None if auth_disabled() else current_user.id,
        action="workspace_member_read",
        payload={
            "returned": len(output),
            "outcome": "success",
        },
    )
    return output


@app.post("/workspaces/{workspace_id}/members", response_model=WorkspaceMemberOut)
def add_workspace_member(
    workspace_id: str,
    payload: WorkspaceMemberAddRequest,
    current_user: UserContext = Depends(get_current_user),
) -> WorkspaceMemberOut:
    workspace_uuid = require_workspace_uuid(workspace_id)
    require_workspace_role(workspace_id, current_user, role="admin")

    with SessionLocal() as session:
        require_workspace_exists(session, workspace_uuid)
        user = session.execute(
            select(UserORM).where(func.lower(UserORM.email) == payload.email)
        ).scalar_one_or_none()
        if user is None:
            domain = payload.email.split("@")[-1] if "@" in payload.email else "unknown"
            log_event(
                workspace_id=workspace_id,
                user_id=None if auth_disabled() else current_user.id,
                action="workspace_member_add",
                payload={
                    "role": payload.role,
                    "target_email_domain": domain,
                    "outcome": "failure",
                    "reason": "target_user_not_found",
                },
            )
            raise HTTPException(
                status_code=400,
                detail="Unable to add workspace member with provided input.",
            )

        existing = session.get(
            WorkspaceMemberORM,
            {
                "workspace_id": workspace_uuid,
                "user_id": user.id,
            },
        )
        if existing is not None:
            domain = payload.email.split("@")[-1] if "@" in payload.email else "unknown"
            log_event(
                workspace_id=workspace_id,
                user_id=None if auth_disabled() else current_user.id,
                action="workspace_member_add",
                payload={
                    "target_user_id": str(user.id),
                    "role": payload.role,
                    "target_email_domain": domain,
                    "outcome": "failure",
                    "reason": "already_member",
                },
            )
            raise HTTPException(
                status_code=400,
                detail="Unable to add workspace member with provided input.",
            )

        membership = WorkspaceMemberORM(
            workspace_id=workspace_uuid,
            user_id=user.id,
            role=payload.role,
        )
        session.add(membership)
        session.commit()
        session.refresh(membership)
        target_user_id = str(user.id)
        target_user_email = user.email
        result = to_workspace_member_out(membership, user)

    domain = target_user_email.split("@")[-1] if "@" in target_user_email else "unknown"
    log_event(
        workspace_id=workspace_id,
        user_id=None if auth_disabled() else current_user.id,
        action="workspace_member_add",
        payload={
            "target_user_id": target_user_id,
            "role": payload.role,
            "target_email_domain": domain,
            "outcome": "success",
        },
    )
    return result


@app.patch(
    "/workspaces/{workspace_id}/members/{user_id}/role",
    response_model=WorkspaceMemberOut,
)
def update_workspace_member_role(
    workspace_id: str,
    user_id: str,
    payload: WorkspaceMemberRoleUpdateRequest,
    current_user: UserContext = Depends(get_current_user),
) -> WorkspaceMemberOut:
    workspace_uuid = require_workspace_uuid(workspace_id)
    user_uuid = require_user_uuid(user_id)
    require_workspace_role(workspace_id, current_user, role="admin")

    with SessionLocal() as session:
        require_workspace_exists(session, workspace_uuid)
        membership = session.get(
            WorkspaceMemberORM,
            {
                "workspace_id": workspace_uuid,
                "user_id": user_uuid,
            },
        )
        if membership is None:
            raise HTTPException(status_code=404, detail="Workspace member not found.")

        old_role = membership.role
        if old_role == "admin" and payload.role != "admin":
            if count_workspace_admins(session, workspace_uuid) <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot demote the last workspace admin.",
                )

        membership.role = payload.role
        session.commit()
        session.refresh(membership)

        user = session.get(UserORM, user_uuid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found.")
        result = to_workspace_member_out(membership, user)

    log_event(
        workspace_id=workspace_id,
        user_id=None if auth_disabled() else current_user.id,
        action="workspace_member_role_update",
        payload={
            "target_user_id": user_id,
            "old_role": old_role,
            "new_role": payload.role,
        },
    )
    return result


@app.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
def remove_workspace_member(
    workspace_id: str,
    user_id: str,
    current_user: UserContext = Depends(get_current_user),
) -> Response:
    workspace_uuid = require_workspace_uuid(workspace_id)
    user_uuid = require_user_uuid(user_id)
    require_workspace_role(workspace_id, current_user, role="admin")

    with SessionLocal() as session:
        require_workspace_exists(session, workspace_uuid)
        membership = session.get(
            WorkspaceMemberORM,
            {
                "workspace_id": workspace_uuid,
                "user_id": user_uuid,
            },
        )
        if membership is None:
            raise HTTPException(status_code=404, detail="Workspace member not found.")

        removed_role = membership.role
        if removed_role == "admin":
            if count_workspace_admins(session, workspace_uuid) <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot remove the last workspace admin.",
                )

        session.delete(membership)
        session.commit()

    log_event(
        workspace_id=workspace_id,
        user_id=None if auth_disabled() else current_user.id,
        action="workspace_member_remove",
        payload={
            "target_user_id": user_id,
            "removed_role": removed_role,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@app.get("/workspaces/{workspace_id}/documents", response_model=list[DocumentInventoryItem])
def list_documents(
    workspace_id: str,
    limit: int = DEFAULT_DOCUMENTS_LIMIT,
    offset: int = 0,
    current_user: UserContext = Depends(get_current_user),
) -> list[DocumentInventoryItem]:
    require_workspace_uuid(workspace_id)
    require_workspace_role(workspace_id, current_user)

    safe_limit = max(1, min(limit, MAX_DOCUMENTS_LIMIT))
    safe_offset = max(0, offset)
    documents = chunk_store.list_documents(
        workspace_id,
        limit=safe_limit,
        offset=safe_offset,
    )
    log_event(
        workspace_id=workspace_id,
        user_id=None if auth_disabled() else current_user.id,
        action="document_inventory_read",
        payload={
            "limit": safe_limit,
            "offset": safe_offset,
            "returned": len(documents),
            "outcome": "success",
        },
    )
    return [to_document_inventory_item(document) for document in documents]


@app.patch(
    "/workspaces/{workspace_id}/documents/{document_id}/classification",
    response_model=DocumentInventoryItem,
)
def update_document_classification(
    workspace_id: str,
    document_id: str,
    payload: DocumentClassificationUpdateRequest,
    current_user: UserContext = Depends(get_current_user),
) -> DocumentInventoryItem:
    require_workspace_uuid(workspace_id)
    require_document_uuid(document_id)
    require_workspace_role(workspace_id, current_user, role="admin")

    document = chunk_store.update_document_classification(
        workspace_id, document_id, payload.classification_label
    )
    if document is None:
        log_event(
            workspace_id=workspace_id,
            user_id=None if auth_disabled() else current_user.id,
            action="document_classification_update",
            payload={
                "document_id": document_id,
                "classification_label": payload.classification_label,
                "outcome": "failure",
                "reason": "document_not_found",
            },
        )
        raise HTTPException(status_code=404, detail="Document not found.")

    log_event(
        workspace_id=workspace_id,
        user_id=None if auth_disabled() else current_user.id,
        action="document_classification_update",
        payload={
            "document_id": document_id,
            "classification_label": payload.classification_label,
            "outcome": "success",
        },
    )
    return to_document_inventory_item(document)


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
