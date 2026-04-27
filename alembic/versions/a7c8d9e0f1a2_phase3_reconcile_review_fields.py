"""Phase 3 — add review metadata to reconcile_flags

Revision ID: a7c8d9e0f1a2
Revises: a7b8c9d0e1f2
Create Date: 2026-04-24
"""

import sqlalchemy as sa

from alembic import op

revision = "a7c8d9e0f1a2"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("reconcile_flags") as batch_op:
        batch_op.add_column(
            sa.Column("agent_reasoning", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column(
                "resolution_options",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[\"keep_existing\", \"use_new\"]'"),
            )
        )
        batch_op.add_column(sa.Column("resolution_choice", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("resolution_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("reconcile_flags") as batch_op:
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("resolution_note")
        batch_op.drop_column("resolution_choice")
        batch_op.drop_column("resolution_options")
        batch_op.drop_column("agent_reasoning")
