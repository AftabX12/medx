"""make reconcile_flags.new_extraction_id nullable

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-20
"""
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("reconcile_flags") as batch_op:
        batch_op.alter_column("new_extraction_id", nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("reconcile_flags") as batch_op:
        batch_op.alter_column("new_extraction_id", nullable=False)
