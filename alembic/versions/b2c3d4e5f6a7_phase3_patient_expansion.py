"""phase 3: patient expanded fields + document pipeline_status

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-18 15:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Patient: contact + clinical + admin fields
    with op.batch_alter_table("patients") as batch_op:
        batch_op.add_column(sa.Column("phone", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("email", sa.String(254), nullable=True))
        batch_op.add_column(sa.Column("address_line1", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("address_line2", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("city", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("state", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("zip_code", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("country", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("blood_type", sa.String(8), nullable=True))
        batch_op.add_column(sa.Column("chief_complaint", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("allergies_summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("emergency_contact_name", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("emergency_contact_phone", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("emergency_contact_relation", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("insurance_provider", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("insurance_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("primary_physician", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("ai_summary", sa.Text(), nullable=True))

    # Document: pipeline_status JSON
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(
            sa.Column("pipeline_status", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("pipeline_status")

    with op.batch_alter_table("patients") as batch_op:
        for col in [
            "phone", "email", "address_line1", "address_line2", "city", "state",
            "zip_code", "country", "blood_type", "chief_complaint", "allergies_summary",
            "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
            "insurance_provider", "insurance_id", "primary_physician", "ai_summary",
        ]:
            batch_op.drop_column(col)
