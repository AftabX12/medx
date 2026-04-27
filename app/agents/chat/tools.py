from __future__ import annotations

import uuid
from contextvars import ContextVar

from sqlalchemy import or_, select

from app.db.models import Allergy, Medication, Observation, Patient, Problem, ReconcileFlag
from app.db.session import SessionLocal

_tenant_id_var: ContextVar[uuid.UUID | None] = ContextVar("chat_tenant_id", default=None)


def set_tool_context(*, tenant_id: str | uuid.UUID):
    return _tenant_id_var.set(_as_uuid(tenant_id))


def reset_tool_context(token) -> None:
    _tenant_id_var.reset(token)


def _tenant_id() -> uuid.UUID:
    tenant_id = _tenant_id_var.get()
    if tenant_id is None:
        raise RuntimeError("chat tool context is missing tenant_id")
    return tenant_id


def _as_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _observation_value(row: Observation) -> str | None:
    if row.value_numeric is not None:
        return str(row.value_numeric.normalize())
    return row.value_text


async def _get_patient(patient_id: str) -> Patient | None:
    tenant_id = _tenant_id()
    try:
        pid = _as_uuid(patient_id)
    except ValueError:
        return None
    async with SessionLocal() as session:
        patient = await session.get(Patient, pid)
        if patient is None or patient.tenant_id != tenant_id:
            return None
        return patient


async def get_patient_summary(patient_id: str) -> str:
    """Get the AI-generated clinical summary for a patient."""
    patient = await _get_patient(patient_id)
    if patient is None:
        return ""
    return patient.ai_summary or ""


async def get_observations(
    patient_id: str,
    label: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Get lab results and vital signs. Optionally filter by label (e.g. 'HbA1c', 'Blood Pressure')."""
    tenant_id = _tenant_id()
    try:
        pid = _as_uuid(patient_id)
    except ValueError:
        return []
    stmt = select(Observation).where(
        Observation.tenant_id == tenant_id,
        Observation.patient_id == pid,
    )
    if label:
        stmt = stmt.where(Observation.label.ilike(f"%{label}%"))
    stmt = stmt.order_by(Observation.effective_date.desc().nullslast()).limit(limit)
    async with SessionLocal() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "label": row.label,
            "value": _observation_value(row),
            "unit": row.unit,
            "date": row.effective_date.isoformat() if row.effective_date else None,
        }
        for row in rows
    ]


async def get_medications(patient_id: str, status: str = "active") -> list[dict]:
    """Get patient medications. Status: 'active', 'discontinued', or 'all'."""
    tenant_id = _tenant_id()
    try:
        pid = _as_uuid(patient_id)
    except ValueError:
        return []
    stmt = select(Medication).where(Medication.tenant_id == tenant_id, Medication.patient_id == pid)
    if status != "all":
        stmt = stmt.where(Medication.status == status)
    stmt = stmt.order_by(Medication.created_at.desc())
    async with SessionLocal() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "name": row.name,
            "dose": row.dose,
            "frequency": row.frequency,
            "route": row.route,
            "status": row.status,
        }
        for row in rows
    ]


async def get_problems(patient_id: str, status: str = "active") -> list[dict]:
    """Get patient's problem list / diagnoses."""
    tenant_id = _tenant_id()
    try:
        pid = _as_uuid(patient_id)
    except ValueError:
        return []
    stmt = select(Problem).where(Problem.tenant_id == tenant_id, Problem.patient_id == pid)
    if status != "all":
        stmt = stmt.where(Problem.status == status)
    stmt = stmt.order_by(Problem.created_at.desc())
    async with SessionLocal() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "label": row.label,
            "status": row.status,
            "icd10_code": row.icd10_code,
        }
        for row in rows
    ]


async def get_allergies(patient_id: str) -> list[dict]:
    """Get patient's known allergies."""
    tenant_id = _tenant_id()
    try:
        pid = _as_uuid(patient_id)
    except ValueError:
        return []
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Allergy)
                .where(Allergy.tenant_id == tenant_id, Allergy.patient_id == pid)
                .order_by(Allergy.created_at.desc())
            )
        ).scalars().all()
    return [
        {"substance": row.substance, "reaction": row.reaction, "severity": row.severity}
        for row in rows
    ]


async def get_pending_flags(patient_id: str) -> list[dict]:
    """Get unresolved reconciliation flags for a patient."""
    tenant_id = _tenant_id()
    try:
        pid = _as_uuid(patient_id)
    except ValueError:
        return []
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ReconcileFlag)
                .where(
                    ReconcileFlag.tenant_id == tenant_id,
                    ReconcileFlag.patient_id == pid,
                    ReconcileFlag.resolved.is_(False),
                )
                .order_by(ReconcileFlag.created_at.desc())
            )
        ).scalars().all()
    return [
        {
            "field": row.details.get("field"),
            "severity": row.severity,
            "current_value": row.details.get("existing_value") or row.details.get("existing"),
            "new_value": row.details.get("document_value") or row.details.get("new"),
            "reasoning": row.agent_reasoning,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


async def search_clinic_patients(query: str, tenant_id: str) -> list[dict]:
    """Search patients in the clinic by name, condition, or medication. Returns brief profiles."""
    context_tenant = _tenant_id()
    try:
        requested_tenant = _as_uuid(tenant_id)
    except ValueError:
        requested_tenant = context_tenant
    if requested_tenant != context_tenant:
        return []

    pattern = f"%{query}%"
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Patient)
                .outerjoin(Problem, Problem.patient_id == Patient.id)
                .outerjoin(Medication, Medication.patient_id == Patient.id)
                .where(
                    Patient.tenant_id == context_tenant,
                    or_(
                        Patient.given_name.ilike(pattern),
                        Patient.family_name.ilike(pattern),
                        Patient.mrn.ilike(pattern),
                        Problem.label.ilike(pattern),
                        Medication.name.ilike(pattern),
                    ),
                )
                .distinct()
                .limit(25)
            )
        ).scalars().all()
    return [
        {
            "patient_id": str(row.id),
            "name": f"{row.given_name} {row.family_name}",
            "mrn": row.mrn,
            "dob": str(row.date_of_birth) if row.date_of_birth else None,
            "summary": row.ai_summary,
        }
        for row in rows
    ]


async def get_patient_demographics(patient_id: str) -> dict:
    """Get patient's demographic information: name, DOB, sex, contact info."""
    patient = await _get_patient(patient_id)
    if patient is None:
        return {}
    return {
        "patient_id": str(patient.id),
        "name": f"{patient.given_name} {patient.family_name}",
        "mrn": patient.mrn,
        "dob": str(patient.date_of_birth) if patient.date_of_birth else None,
        "sex": patient.sex,
        "phone": patient.phone,
        "email": patient.email,
        "address": {
            "line1": patient.address_line1,
            "line2": patient.address_line2,
            "city": patient.city,
            "state": patient.state,
            "zip_code": patient.zip_code,
            "country": patient.country,
        },
        "insurance_provider": patient.insurance_provider,
        "insurance_id": patient.insurance_id,
    }
