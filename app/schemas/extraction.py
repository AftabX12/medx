import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    field_type: str
    value_normalized: dict[str, Any]
    confidence: float | None
    extracted_by_model: str | None
    created_at: datetime


class ReconcileFlagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    document_id: uuid.UUID
    kind: str
    resource_type: str
    existing_id: uuid.UUID | None
    new_extraction_id: uuid.UUID
    details: dict[str, Any]
    resolved: bool
    created_at: datetime
