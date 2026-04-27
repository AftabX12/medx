from __future__ import annotations

import uuid
from contextvars import ContextVar

from sqlalchemy import select

from app.db.models import Allergy, Medication, Observation, Patient, Problem, ReconcileFlag
from app.db.session import SessionLocal

_tenant_id_var: ContextVar[uuid.UUID | None] = ContextVar("clinical_summary_tenant_id", default=None)


def set_tool_context(*, tenant_id: str | uuid.UUID):
    return _tenant_id_var.set(_as_uuid(tenant_id))


def reset_tool_context(token) -> None:
    _tenant_id_var.reset(token)


def _tenant_id() -> uuid.UUID:
    tenant_id = _tenant_id_var.get()
    if tenant_id is None:
        raise RuntimeError("clinical summary tool context is missing tenant_id")
    return tenant_id


def _as_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _observation_value(row: Observation) -> str | None:
    if row.value_numeric is not None:
        return str(row.value_numeric.normalize())
    return row.value_text


async def get_patient_full_context(patient_id: str) -> dict:
    """Get complete patient record for summary generation: demographics, all active problems,
    all active medications, allergies, and the 20 most recent observations."""
    tenant_id = _tenant_id()
    pid = _as_uuid(patient_id)
    async with SessionLocal() as session:
        patient = await session.get(Patient, pid)
        if patient is None or patient.tenant_id != tenant_id:
            return {}

        problems = (
            await session.execute(
                select(Problem)
                .where(
                    Problem.tenant_id == tenant_id,
                    Problem.patient_id == pid,
                    Problem.status == "active",
                )
                .order_by(Problem.created_at.desc())
            )
        ).scalars().all()
        medications = (
            await session.execute(
                select(Medication)
                .where(
                    Medication.tenant_id == tenant_id,
                    Medication.patient_id == pid,
                    Medication.status == "active",
                )
                .order_by(Medication.created_at.desc())
            )
        ).scalars().all()
        allergies = (
            await session.execute(
                select(Allergy)
                .where(Allergy.tenant_id == tenant_id, Allergy.patient_id == pid)
                .order_by(Allergy.created_at.desc())
            )
        ).scalars().all()
        observations = (
            await session.execute(
                select(Observation)
                .where(Observation.tenant_id == tenant_id, Observation.patient_id == pid)
                .order_by(Observation.effective_date.desc().nullslast())
                .limit(20)
            )
        ).scalars().all()

    return {
        "patient": {
            "id": str(patient.id),
            "name": f"{patient.given_name} {patient.family_name}",
            "dob": str(patient.date_of_birth) if patient.date_of_birth else None,
            "sex": patient.sex,
            "mrn": patient.mrn,
            "blood_type": patient.blood_type,
            "allergies_summary": patient.allergies_summary,
        },
        "active_problems": [
            {"label": row.label, "status": row.status, "icd10_code": row.icd10_code}
            for row in problems
        ],
        "active_medications": [
            {
                "name": row.name,
                "dose": row.dose,
                "frequency": row.frequency,
                "route": row.route,
                "status": row.status,
            }
            for row in medications
        ],
        "allergies": [
            {
                "substance": row.substance,
                "reaction": row.reaction,
                "severity": row.severity,
            }
            for row in allergies
        ],
        "recent_observations": [
            {
                "label": row.label,
                "value": _observation_value(row),
                "unit": row.unit,
                "date": row.effective_date.isoformat() if row.effective_date else None,
            }
            for row in observations
        ],
    }


async def get_recent_document_changes(patient_id: str, document_id: str) -> dict:
    """Get what was added or updated when the most recent document was processed."""
    tenant_id = _tenant_id()
    pid = _as_uuid(patient_id)
    did = _as_uuid(document_id)
    async with SessionLocal() as session:
        observations = (
            await session.execute(
                select(Observation)
                .where(
                    Observation.tenant_id == tenant_id,
                    Observation.patient_id == pid,
                    Observation.source_document_id == did,
                )
                .order_by(Observation.created_at.desc())
            )
        ).scalars().all()
        medications = (
            await session.execute(
                select(Medication)
                .where(
                    Medication.tenant_id == tenant_id,
                    Medication.patient_id == pid,
                    Medication.source_document_id == did,
                )
                .order_by(Medication.created_at.desc())
            )
        ).scalars().all()
        problems = (
            await session.execute(
                select(Problem)
                .where(
                    Problem.tenant_id == tenant_id,
                    Problem.patient_id == pid,
                    Problem.source_document_id == did,
                )
                .order_by(Problem.created_at.desc())
            )
        ).scalars().all()
        allergies = (
            await session.execute(
                select(Allergy)
                .where(
                    Allergy.tenant_id == tenant_id,
                    Allergy.patient_id == pid,
                    Allergy.source_document_id == did,
                )
                .order_by(Allergy.created_at.desc())
            )
        ).scalars().all()
        flags = (
            await session.execute(
                select(ReconcileFlag)
                .where(
                    ReconcileFlag.tenant_id == tenant_id,
                    ReconcileFlag.patient_id == pid,
                    ReconcileFlag.document_id == did,
                )
                .order_by(ReconcileFlag.created_at.desc())
            )
        ).scalars().all()

    return {
        "observations_added": [
            {"label": row.label, "value": _observation_value(row), "unit": row.unit}
            for row in observations
        ],
        "medications_added_or_updated": [
            {
                "name": row.name,
                "dose": row.dose,
                "frequency": row.frequency,
                "status": row.status,
            }
            for row in medications
        ],
        "problems_added": [
            {"label": row.label, "status": row.status, "icd10_code": row.icd10_code}
            for row in problems
        ],
        "allergies_added": [
            {"substance": row.substance, "reaction": row.reaction, "severity": row.severity}
            for row in allergies
        ],
        "flags": [
            {
                "flag_id": str(row.id),
                "field": row.details.get("field"),
                "severity": row.severity,
                "resolution_choice": row.resolution_choice,
                "resolution_note": row.resolution_note,
                "resolved": row.resolved,
                "reasoning": row.agent_reasoning,
            }
            for row in flags
        ],
    }
