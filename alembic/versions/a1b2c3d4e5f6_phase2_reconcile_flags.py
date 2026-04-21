"""phase 2: reconcile_flags table

Revision ID: a1b2c3d4e5f6
Revises: 3e5cd5ca4177
Create Date: 2026-04-18 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "3e5cd5ca4177"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reconcile_flags",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("existing_id", sa.Uuid(), nullable=True),
        sa.Column("new_extraction_id", sa.Uuid(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["new_extraction_id"], ["extractions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reconcile_flags_tenant_id", "reconcile_flags", ["tenant_id"]
    )
    op.create_index(
        "ix_reconcile_flags_patient_id", "reconcile_flags", ["patient_id"]
    )
    op.create_index(
        "ix_reconcile_flags_document_id", "reconcile_flags", ["document_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_reconcile_flags_document_id", table_name="reconcile_flags")
    op.drop_index("ix_reconcile_flags_patient_id", table_name="reconcile_flags")
    op.drop_index("ix_reconcile_flags_tenant_id", table_name="reconcile_flags")
    op.drop_table("reconcile_flags")
