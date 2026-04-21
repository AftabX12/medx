"""ReconcileFlag: non-destructive duplicate/conflict markers for extracted records."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Uuid
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
    # Phase 3.1: severity (critical/warning/info), tier (1=rule, 2=LLM), resolved_by
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    resolved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
