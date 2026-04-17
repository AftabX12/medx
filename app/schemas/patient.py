import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PatientCreate(BaseModel):
    mrn: str = Field(min_length=1, max_length=64)
    given_name: str = Field(min_length=1, max_length=120)
    family_name: str = Field(min_length=1, max_length=120)
    date_of_birth: date | None = None
    sex: str | None = Field(default=None, max_length=16)
    demographics: dict = Field(default_factory=dict)


class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mrn: str
    given_name: str
    family_name: str
    date_of_birth: date | None
    sex: str | None
    demographics: dict
    created_at: datetime
