"""Patient REST API — CRUD for patient demographic records."""
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.db.models import Patient
from app.db.repositories.patient import PatientRepository
from app.deps import CurrentUser, SessionDep
from app.schemas.patient import PatientCreate, PatientResponse, PatientUpdate

router = APIRouter(prefix="/patients", tags=["patients"])

_CREATE_FIELDS = [
    "mrn", "given_name", "family_name", "date_of_birth", "sex", "demographics",
    "phone", "email", "address_line1", "address_line2", "city", "state",
    "zip_code", "country", "blood_type", "chief_complaint", "allergies_summary",
    "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
    "insurance_provider", "insurance_id", "primary_physician",
]


@router.post("", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(body: PatientCreate, session: SessionDep, user: CurrentUser) -> Patient:
    repo = PatientRepository(session, user.tenant_id)
    patient = Patient(tenant_id=user.tenant_id, **{f: getattr(body, f) for f in _CREATE_FIELDS})
    try:
        await repo.add(patient)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="patient with that MRN already exists") from None
    await session.refresh(patient)
    return patient


@router.get("", response_model=list[PatientResponse])
async def list_patients(session: SessionDep, user: CurrentUser, limit: int = 100, offset: int = 0):
    return await PatientRepository(session, user.tenant_id).list(limit=limit, offset=offset)


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(patient_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Patient:
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient not found")
    return patient


@router.patch("/{patient_id}", response_model=PatientResponse)
async def update_patient(
    patient_id: uuid.UUID, body: PatientUpdate, session: SessionDep, user: CurrentUser
) -> Patient:
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)
    await session.commit()
    await session.refresh(patient)
    return patient


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient(patient_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> None:
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient not found")
    await session.delete(patient)
    await session.commit()
