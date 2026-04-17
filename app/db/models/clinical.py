import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, TimestampMixin


def _tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def _patient_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        Uuid,
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class Observation(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "observations"

    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    patient_id: Mapped[uuid.UUID] = _patient_fk()
    loinc_code: Mapped[str | None] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(64))
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="SET NULL"),
    )


class Medication(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "medications"

    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    patient_id: Mapped[uuid.UUID] = _patient_fk()
    rxnorm_code: Mapped[str | None] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dose: Mapped[str | None] = mapped_column(String(128))
    frequency: Mapped[str | None] = mapped_column(String(128))
    route: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="SET NULL"),
    )


class Problem(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "problems"

    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    patient_id: Mapped[uuid.UUID] = _patient_fk()
    icd10_code: Mapped[str | None] = mapped_column(String(16), index=True)
    snomed_code: Mapped[str | None] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    onset_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="SET NULL"),
    )


class Allergy(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "allergies"

    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    patient_id: Mapped[uuid.UUID] = _patient_fk()
    substance: Mapped[str] = mapped_column(String(200), nullable=False)
    reaction: Mapped[str | None] = mapped_column(String(200))
    severity: Mapped[str | None] = mapped_column(String(32))
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="SET NULL"),
    )


class Encounter(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "encounters"

    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    patient_id: Mapped[uuid.UUID] = _patient_fk()
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    encounter_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    visit_type: Mapped[str | None] = mapped_column(String(64))
    note_markdown: Mapped[str | None] = mapped_column(Text)
