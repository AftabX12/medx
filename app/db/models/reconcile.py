"""ReconcileFlag: non-destructive duplicate/conflict markers for extracted records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, TimestampMixin


class ReconcileFlag(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "reconcile_flags"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    existing_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    new_extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("extractions.id", ondelete="CASCADE"),
        nullable=True,
    )
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Phase 3.1: severity (critical/warning/info), tier (1=rule, 2=LLM), resolved_by
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    resolved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agent_reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolution_options: Mapped[list] = mapped_column(
        JSON, nullable=False, default=lambda: ["keep_existing", "use_new"]
    )
    resolution_choice: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
