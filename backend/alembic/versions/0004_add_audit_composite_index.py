"""add composite audit index

Revision ID: 0004
Revises: 0003
Create Date: 2026-02-04
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_workspace_id")
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_created_at")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_workspace_created_at "
        "ON audit_logs (workspace_id, created_at DESC)"
    )


def downgrade() -> None:
    # 0003 now defines the composite index, so downgrading keeps the same shape.
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_workspace_id")
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_created_at")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_workspace_created_at "
        "ON audit_logs (workspace_id, created_at DESC)"
    )
