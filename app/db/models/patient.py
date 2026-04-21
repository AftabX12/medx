import uuid
from datetime import date

from sqlalchemy import JSON, Date, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, TimestampMixin


class Patient(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "patients"
    __table_args__ = (UniqueConstraint("tenant_id", "mrn", name="uq_patients_tenant_mrn"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    mrn: Mapped[str] = mapped_column(String(64), nullable=False)
    given_name: Mapped[str] = mapped_column(String(120), nullable=False)
    family_name: Mapped[str] = mapped_column(String(120), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(16))
    demographics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Contact
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(254))
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    zip_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(100))

    # Clinical
    blood_type: Mapped[str | None] = mapped_column(String(8))
    chief_complaint: Mapped[str | None] = mapped_column(Text)
    allergies_summary: Mapped[str | None] = mapped_column(Text)

    # Emergency contact
    emergency_contact_name: Mapped[str | None] = mapped_column(String(200))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(32))
    emergency_contact_relation: Mapped[str | None] = mapped_column(String(64))

    # Insurance / administrative
    insurance_provider: Mapped[str | None] = mapped_column(String(200))
    insurance_id: Mapped[str | None] = mapped_column(String(64))
    primary_physician: Mapped[str | None] = mapped_column(String(200))

    # Pipeline status: tracks per-step agent progress for each document
    # Stored on Document, not here — but we keep a summary JSON for the patient summary
    ai_summary: Mapped[str | None] = mapped_column(Text)
