"""Phase 3.1 — add severity, tier, resolved_by to reconcile_flags

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-18
"""

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reconcile_flags",
        sa.Column("severity", sa.String(16), nullable=False, server_default="warning"),
    )
    op.add_column(
        "reconcile_flags",
        sa.Column("tier", sa.Integer, nullable=False, server_default="2"),
    )
    op.add_column(
        "reconcile_flags",
        sa.Column("resolved_by", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reconcile_flags", "resolved_by")
    op.drop_column("reconcile_flags", "tier")
    op.drop_column("reconcile_flags", "severity")
