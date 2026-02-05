"""add document classification label

Revision ID: 0005
Revises: 0004
Create Date: 2026-02-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "classification_label",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'internal'"),
        ),
    )
    op.create_check_constraint(
        "ck_documents_classification_label",
        "documents",
        "classification_label IN ('public', 'internal', 'confidential', 'restricted')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_documents_classification_label",
        "documents",
        type_="check",
    )
    op.drop_column("documents", "classification_label")
