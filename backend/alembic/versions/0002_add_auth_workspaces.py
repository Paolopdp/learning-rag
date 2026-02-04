"""add auth and workspaces

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-04
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
SYSTEM_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "workspaces",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "workspace_members",
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )

    op.add_column(
        "documents",
        sa.Column(
            "workspace_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "chunks",
        sa.Column(
            "workspace_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO users (id, email, hashed_password) VALUES (:id, :email, :hashed)"
        ),
        {
            "id": SYSTEM_USER_ID,
            "email": "system@local",
            "hashed": "!disabled!",
        },
    )
    conn.execute(
        sa.text("INSERT INTO workspaces (id, name) VALUES (:id, :name)"),
        {
            "id": SYSTEM_WORKSPACE_ID,
            "name": "System Workspace",
        },
    )
    conn.execute(
        sa.text(
            "INSERT INTO workspace_members (user_id, workspace_id, role) VALUES (:user_id, :workspace_id, :role)"
        ),
        {
            "user_id": SYSTEM_USER_ID,
            "workspace_id": SYSTEM_WORKSPACE_ID,
            "role": "admin",
        },
    )

    conn.execute(
        sa.text(
            "UPDATE documents SET workspace_id = :workspace_id WHERE workspace_id IS NULL"
        ),
        {"workspace_id": SYSTEM_WORKSPACE_ID},
    )
    conn.execute(
        sa.text("UPDATE chunks SET workspace_id = :workspace_id WHERE workspace_id IS NULL"),
        {"workspace_id": SYSTEM_WORKSPACE_ID},
    )

    op.alter_column("documents", "workspace_id", nullable=False)
    op.alter_column("chunks", "workspace_id", nullable=False)


def downgrade() -> None:
    op.drop_column("chunks", "workspace_id")
    op.drop_column("documents", "workspace_id")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    op.drop_table("users")
