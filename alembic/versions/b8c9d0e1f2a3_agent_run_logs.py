"""Phase 7 — agent run logs for optimization trainsets

Revision ID: b8c9d0e1f2a3
Revises: a7c8d9e0f1a2
Create Date: 2026-04-24
"""

import sqlalchemy as sa

from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "a7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_run_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("inputs_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("outputs_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("tool_calls", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_run_logs_tenant_id", "agent_run_logs", ["tenant_id"])
    op.create_index("ix_agent_run_logs_document_id", "agent_run_logs", ["document_id"])
    op.create_index("ix_agent_run_logs_agent_name", "agent_run_logs", ["agent_name"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_logs_agent_name", table_name="agent_run_logs")
    op.drop_index("ix_agent_run_logs_document_id", table_name="agent_run_logs")
    op.drop_index("ix_agent_run_logs_tenant_id", table_name="agent_run_logs")
    op.drop_table("agent_run_logs")
