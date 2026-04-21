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
    phone: str | None = None
    email: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country: str | None = None
    blood_type: str | None = None
    chief_complaint: str | None = None
    allergies_summary: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    emergency_contact_relation: str | None = None
    insurance_provider: str | None = None
    insurance_id: str | None = None
    primary_physician: str | None = None


class PatientUpdate(BaseModel):
    given_name: str | None = Field(default=None, max_length=120)
    family_name: str | None = Field(default=None, max_length=120)
    date_of_birth: date | None = None
    sex: str | None = Field(default=None, max_length=16)
    demographics: dict | None = None
    phone: str | None = None
    email: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country: str | None = None
    blood_type: str | None = None
    chief_complaint: str | None = None
    allergies_summary: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    emergency_contact_relation: str | None = None
    insurance_provider: str | None = None
    insurance_id: str | None = None
    primary_physician: str | None = None


class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mrn: str
    given_name: str
    family_name: str
    date_of_birth: date | None
    sex: str | None
    demographics: dict
    phone: str | None
    email: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    country: str | None
    blood_type: str | None
    chief_complaint: str | None
    allergies_summary: str | None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    emergency_contact_relation: str | None
    insurance_provider: str | None
    insurance_id: str | None
    primary_physician: str | None
    ai_summary: str | None
    created_at: datetime
