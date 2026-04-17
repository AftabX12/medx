import uuid
from datetime import date

from sqlalchemy import JSON, Date, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, TimestampMixin


class Patient(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "patients"
    __table_args__ = (UniqueConstraint("tenant_id", "mrn", name="uq_patients_tenant_mrn"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mrn: Mapped[str] = mapped_column(String(64), nullable=False)
    given_name: Mapped[str] = mapped_column(String(120), nullable=False)
    family_name: Mapped[str] = mapped_column(String(120), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(16))
    demographics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
