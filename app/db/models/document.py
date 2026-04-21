"""Document and Extraction models.

Document represents an uploaded file (PDF or image). Its lifecycle is tracked
through two fields:
  - ocr_status: "pending" → "ok" | "failed" | "no_text" | "unsupported"
  - pipeline_status: JSON dict of per-step state:
      {"ocr": {"status": "ok"}, "classify": {"status": "ok", "detail": "lab_panel"}, ...}

Extraction is an audit record of a single LLM extraction pass. The raw payload
(value_normalized) is kept verbatim so the UI can show exactly what the model
returned, independent of what was persisted to clinical tables.
"""

import uuid

from sqlalchemy import JSON, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, TimestampMixin


class Document(Base, PrimaryKeyMixin, TimestampMixin):
    """An uploaded clinical document.

    file_key is content-addressable (SHA-256 of file bytes) within the tenant's
    storage directory. Duplicate uploads of the same file return the existing
    Document row rather than creating a new one.

    pipeline_status tracks the 6-step AI pipeline per step:
        ocr | classify | extract | persist | profile | summarize
    Each step value is a dict: {"status": "ok"|"running"|"failed"|"skipped", "detail": "..."}
    """

    __tablename__ = "documents"

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
    # "upload" | "patient_upload" | "fax" | "hl7"
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Set by the classify step: "lab_panel" | "imaging_report" | "discharge_summary" |
    # "med_list" | "history_physical" | "other"
    doc_type: Mapped[str | None] = mapped_column(String(64))
    file_key: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    original_filename: Mapped[str | None] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    # "pending" | "ok" | "failed" | "no_text" | "unsupported"
    ocr_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    ocr_text: Mapped[str | None] = mapped_column(Text)
    # Per-step pipeline tracking; updated in-place by the AI pipeline workers
    pipeline_status: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class Extraction(Base, PrimaryKeyMixin, TimestampMixin):
    """Audit record of a single LLM extraction pass on a document.

    value_normalized stores the complete JSON payload returned by the model
    (post schema-validation). This is the source of truth for the structured
    extraction pane in the document viewer.

    One Document may have multiple Extraction rows if re-extraction is run
    (each pipeline run appends a new row; old rows are never overwritten).
    """

    __tablename__ = "extractions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Matches DocType.value: "lab_panel" | "imaging_report" | etc.
    field_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value_raw: Mapped[str | None] = mapped_column(Text)
    # Full parsed JSON payload from the LLM
    value_normalized: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    code_system: Mapped[str | None] = mapped_column(String(32))
    code: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    extracted_by_model: Mapped[str | None] = mapped_column(String(128))
