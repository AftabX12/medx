import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    source_type: str
    doc_type: str | None
    original_filename: str | None
    mime_type: str | None
    file_hash: str
    ocr_status: str
    created_at: datetime
