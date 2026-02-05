from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.auth import UserContext
from app.main import (
    add_workspace_member,
    list_workspace_members,
    remove_workspace_member,
    update_workspace_member_role,
)
from app.schemas import WorkspaceMemberAddRequest, WorkspaceMemberRoleUpdateRequest
from app.sql_models import UserORM, WorkspaceMemberORM, WorkspaceORM


class _ScalarOneResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class _ScalarOneOrNoneResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _ScalarsResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _ExecuteResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values

    def scalars(self):
        return _ScalarsResult(self._values)


class _FakeSession:
    def __init__(self, users, memberships, workspaces):
        self.users = users
        self.memberships = memberships
        self.workspaces = workspaces

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def execute(self, statement):
        sql = str(statement)
        params = statement.compile().params

        if "FROM users" in sql and "users.email" in sql:
            email = next((value for value in params.values() if isinstance(value, str)), None)
            user = next((value for value in self.users.values() if value.email == email), None)
            return _ScalarOneOrNoneResult(user)

        if (
            "FROM workspace_members" in sql
            and "JOIN users" in sql
            and "ORDER BY workspace_members.created_at ASC" in sql
        ):
            workspace_id = next(
                (value for value in params.values() if isinstance(value, uuid.UUID)),
                None,
            )
            rows = [
                (membership, self.users.get(user_id))
                for (ws_id, _), membership in self.memberships.items()
                for user_id in [membership.user_id]
                if ws_id == workspace_id
            ]
            rows.sort(key=lambda row: row[0].created_at)
            return _ExecuteResult(rows)

        if "count(" in sql and "workspace_members.role" in sql:
            workspace_id = next(
                (value for value in params.values() if isinstance(value, uuid.UUID)),
                None,
            )
            role = next((value for value in params.values() if isinstance(value, str)), None)
            count = sum(
                1
                for (ws_id, _), membership in self.memberships.items()
                if ws_id == workspace_id and membership.role == role
            )
            return _ScalarOneResult(count)

        raise AssertionError(f"Unexpected statement: {sql}")

    def get(self, model, key):
        if model is UserORM:
            return self.users.get(key)
        if model is WorkspaceORM:
            return self.workspaces.get(key)
        if model is WorkspaceMemberORM:
            if isinstance(key, dict):
                return self.memberships.get((key["workspace_id"], key["user_id"]))
        raise AssertionError(f"Unexpected get call: model={model} key={key}")

    def add(self, value):
        if isinstance(value, WorkspaceMemberORM):
            if value.created_at is None:
                value.created_at = datetime.now(timezone.utc)
            self.memberships[(value.workspace_id, value.user_id)] = value
            return
        raise AssertionError(f"Unexpected add value: {value}")

    def commit(self):
        return None

    def refresh(self, value):
        if isinstance(value, WorkspaceMemberORM) and value.created_at is None:
            value.created_at = datetime.now(timezone.utc)
        return None

    def delete(self, value):
        if isinstance(value, WorkspaceMemberORM):
            self.memberships.pop((value.workspace_id, value.user_id), None)
            return
        raise AssertionError(f"Unexpected delete value: {value}")


class _FakeSessionLocal:
    def __init__(self, users, memberships, workspaces):
        self.users = users
        self.memberships = memberships
        self.workspaces = workspaces

    def __call__(self):
        return _FakeSession(self.users, self.memberships, self.workspaces)


def _build_user(user_id: uuid.UUID, email: str) -> UserORM:
    user = UserORM(email=email, hashed_password="hash")
    user.id = user_id
    return user


def _build_membership(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
) -> WorkspaceMemberORM:
    membership = WorkspaceMemberORM(
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
    )
    membership.created_at = datetime.now(timezone.utc)
    return membership


def _build_workspace(workspace_id: uuid.UUID, name: str = "Workspace") -> WorkspaceORM:
    workspace = WorkspaceORM(name=name)
    workspace.id = workspace_id
    return workspace


def _setup_members_env(monkeypatch: pytest.MonkeyPatch):
    from app import main

    workspace_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    admin_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    member_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    users = {
        admin_id: _build_user(admin_id, "admin@local"),
        member_id: _build_user(member_id, "member@local"),
    }
    memberships = {
        (workspace_id, admin_id): _build_membership(workspace_id, admin_id, "admin"),
    }
    workspaces = {
        workspace_id: _build_workspace(workspace_id),
    }

    monkeypatch.setattr(main, "SessionLocal", _FakeSessionLocal(users, memberships, workspaces))
    monkeypatch.setattr(main, "require_workspace_role", lambda *args, **kwargs: "admin")

    events = []
    monkeypatch.setattr(main, "log_event", lambda **kwargs: events.append(kwargs))

    current_user = UserContext(id=str(admin_id), email="admin@local")
    return {
        "workspace_id": workspace_id,
        "admin_id": admin_id,
        "member_id": member_id,
        "memberships": memberships,
        "workspaces": workspaces,
        "events": events,
        "current_user": current_user,
    }


def test_add_workspace_member_and_list(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _setup_members_env(monkeypatch)

    added = add_workspace_member(
        workspace_id=str(ctx["workspace_id"]),
        payload=WorkspaceMemberAddRequest(email="member@local", role="member"),
        current_user=ctx["current_user"],
    )
    assert added.email == "member@local"
    assert added.role == "member"

    members = list_workspace_members(
        workspace_id=str(ctx["workspace_id"]),
        current_user=ctx["current_user"],
    )
    assert len(members) == 2
    assert {member.email for member in members} == {"admin@local", "member@local"}
    assert any(event["action"] == "workspace_member_add" for event in ctx["events"])
    read_events = [
        event for event in ctx["events"] if event["action"] == "workspace_member_read"
    ]
    assert len(read_events) == 1
    assert read_events[0]["payload"]["outcome"] == "success"
    assert read_events[0]["payload"]["returned"] == 2


def test_update_workspace_member_role_blocks_last_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _setup_members_env(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        update_workspace_member_role(
            workspace_id=str(ctx["workspace_id"]),
            user_id=str(ctx["admin_id"]),
            payload=WorkspaceMemberRoleUpdateRequest(role="member"),
            current_user=ctx["current_user"],
        )

    assert exc.value.status_code == 400
    assert "last workspace admin" in exc.value.detail


def test_remove_workspace_member_success(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _setup_members_env(monkeypatch)
    workspace_id = ctx["workspace_id"]
    member_id = ctx["member_id"]
    ctx["memberships"][(workspace_id, member_id)] = _build_membership(
        workspace_id,
        member_id,
        "member",
    )

    response = remove_workspace_member(
        workspace_id=str(workspace_id),
        user_id=str(member_id),
        current_user=ctx["current_user"],
    )

    assert response.status_code == 204
    assert (workspace_id, member_id) not in ctx["memberships"]
    assert ctx["events"][-1]["action"] == "workspace_member_remove"


def test_remove_workspace_member_blocks_last_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _setup_members_env(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        remove_workspace_member(
            workspace_id=str(ctx["workspace_id"]),
            user_id=str(ctx["admin_id"]),
            current_user=ctx["current_user"],
        )

    assert exc.value.status_code == 400
    assert "last workspace admin" in exc.value.detail


def test_add_workspace_member_unknown_email_uses_generic_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _setup_members_env(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        add_workspace_member(
            workspace_id=str(ctx["workspace_id"]),
            payload=WorkspaceMemberAddRequest(email="missing@local", role="member"),
            current_user=ctx["current_user"],
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Unable to add workspace member with provided input."
    assert ctx["events"][-1]["action"] == "workspace_member_add"
    assert ctx["events"][-1]["payload"]["outcome"] == "failure"
    assert ctx["events"][-1]["payload"]["reason"] == "target_user_not_found"


def test_add_workspace_member_requires_existing_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _setup_members_env(monkeypatch)
    ctx["workspaces"].pop(ctx["workspace_id"])

    with pytest.raises(HTTPException) as exc:
        add_workspace_member(
            workspace_id=str(ctx["workspace_id"]),
            payload=WorkspaceMemberAddRequest(email="member@local", role="member"),
            current_user=ctx["current_user"],
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Workspace not found."


def test_list_workspace_members_fails_on_missing_user_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _setup_members_env(monkeypatch)
    missing_user_id = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    ctx["memberships"][(ctx["workspace_id"], missing_user_id)] = _build_membership(
        ctx["workspace_id"],
        missing_user_id,
        "member",
    )

    with pytest.raises(HTTPException) as exc:
        list_workspace_members(
            workspace_id=str(ctx["workspace_id"]),
            current_user=ctx["current_user"],
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == "Workspace membership data integrity error."
    read_events = [
        event for event in ctx["events"] if event["action"] == "workspace_member_read"
    ]
    assert len(read_events) == 1
    assert read_events[0]["payload"]["outcome"] == "failure"
    assert read_events[0]["payload"]["reason"] == "missing_user_record"
    assert read_events[0]["payload"]["missing_user_id"] == str(missing_user_id)


def test_workspace_member_add_request_normalizes_email() -> None:
    payload = WorkspaceMemberAddRequest(email="  Member@Example.Org  ", role="member")
    assert payload.email == "member@example.org"


def test_workspace_member_add_request_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        WorkspaceMemberAddRequest(email="invalid-email", role="member")
