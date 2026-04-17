import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.db.models import Patient
from app.db.repositories.patient import PatientRepository
from app.deps import CurrentUser, SessionDep
from app.schemas.patient import PatientCreate, PatientResponse

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(
    body: PatientCreate,
    session: SessionDep,
    user: CurrentUser,
) -> Patient:
    repo = PatientRepository(session, user.tenant_id)
    patient = Patient(
        tenant_id=user.tenant_id,
        mrn=body.mrn,
        given_name=body.given_name,
        family_name=body.family_name,
        date_of_birth=body.date_of_birth,
        sex=body.sex,
        demographics=body.demographics,
    )
    try:
        await repo.add(patient)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="patient with that MRN already exists"
        ) from None
    await session.refresh(patient)
    return patient


@router.get("", response_model=list[PatientResponse])
async def list_patients(
    session: SessionDep,
    user: CurrentUser,
    limit: int = 100,
    offset: int = 0,
) -> list[Patient]:
    repo = PatientRepository(session, user.tenant_id)
    return await repo.list(limit=limit, offset=offset)


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> Patient:
    repo = PatientRepository(session, user.tenant_id)
    patient = await repo.get(patient_id)
    if not patient:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient not found")
    return patient
