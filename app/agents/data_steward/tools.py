from __future__ import annotations

import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select

from app.db.models import (
    Allergy,
    Document,
    Medication,
    Observation,
    Patient,
    Problem,
    ReconcileFlag,
)
from app.db.session import SessionLocal

_tenant_id_var: ContextVar[uuid.UUID | None] = ContextVar("data_steward_tenant_id", default=None)


def set_tool_context(*, tenant_id: str | uuid.UUID):
    return _tenant_id_var.set(_as_uuid(tenant_id))


def reset_tool_context(token) -> None:
    _tenant_id_var.reset(token)


def _tenant_id() -> uuid.UUID:
    tenant_id = _tenant_id_var.get()
    if tenant_id is None:
        raise RuntimeError("data steward tool context is missing tenant_id")
    return tenant_id


def _as_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _normalise(value: object) -> str:
    return str(value or "").strip().lower()


def _serialise_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _value_for_observation(row: Observation) -> str | None:
    if row.value_numeric is not None:
        return str(row.value_numeric.normalize())
    return row.value_text


def _to_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _parse_observation_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def get_patient_record(patient_id: str) -> dict:
    """Get demographics, active clinical lists, and recent observations."""
    tenant_id = _tenant_id()
    pid = _as_uuid(patient_id)
    async with SessionLocal() as session:
        patient = await session.get(Patient, pid)
        if patient is None or patient.tenant_id != tenant_id:
            return {}

        observations = (
            await session.execute(
                select(Observation)
                .where(Observation.tenant_id == tenant_id, Observation.patient_id == pid)
                .order_by(Observation.effective_date.desc().nullslast())
                .limit(50)
            )
        ).scalars().all()
        medications = (
            await session.execute(
                select(Medication)
                .where(Medication.tenant_id == tenant_id, Medication.patient_id == pid)
                .order_by(Medication.created_at.desc())
            )
        ).scalars().all()
        problems = (
            await session.execute(
                select(Problem)
                .where(Problem.tenant_id == tenant_id, Problem.patient_id == pid)
                .order_by(Problem.created_at.desc())
            )
        ).scalars().all()
        allergies = (
            await session.execute(
                select(Allergy)
                .where(Allergy.tenant_id == tenant_id, Allergy.patient_id == pid)
                .order_by(Allergy.created_at.desc())
            )
        ).scalars().all()

    return {
        "patient": {
            "id": str(patient.id),
            "mrn": patient.mrn,
            "given_name": patient.given_name,
            "family_name": patient.family_name,
            "date_of_birth": str(patient.date_of_birth) if patient.date_of_birth else None,
            "sex": patient.sex,
            "phone": patient.phone,
            "email": patient.email,
            "address_line1": patient.address_line1,
            "address_line2": patient.address_line2,
            "city": patient.city,
            "state": patient.state,
            "zip_code": patient.zip_code,
            "country": patient.country,
            "blood_type": patient.blood_type,
            "insurance_provider": patient.insurance_provider,
            "insurance_id": patient.insurance_id,
            "primary_physician": patient.primary_physician,
        },
        "observations": [
            {
                "label": o.label,
                "value": _value_for_observation(o),
                "unit": o.unit,
                "date": _serialise_dt(o.effective_date),
            }
            for o in observations
        ],
        "medications": [
            {
                "id": str(m.id),
                "name": m.name,
                "dose": m.dose,
                "frequency": m.frequency,
                "route": m.route,
                "status": m.status,
            }
            for m in medications
        ],
        "problems": [
            {"id": str(p.id), "label": p.label, "status": p.status, "icd10_code": p.icd10_code}
            for p in problems
        ],
        "allergies": [
            {"id": str(a.id), "substance": a.substance, "reaction": a.reaction, "severity": a.severity}
            for a in allergies
        ],
    }


async def get_observation_history(patient_id: str, label: str, limit: int = 10) -> list[dict]:
    """Return historical values for one observation label, oldest to newest."""
    tenant_id = _tenant_id()
    pid = _as_uuid(patient_id)
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Observation)
                .where(
                    Observation.tenant_id == tenant_id,
                    Observation.patient_id == pid,
                    func.lower(Observation.label) == label.lower(),
                )
                .order_by(Observation.effective_date.desc().nullslast())
                .limit(limit)
            )
        ).scalars().all()
    return [
        {"value": _value_for_observation(row), "unit": row.unit, "date": _serialise_dt(row.effective_date)}
        for row in reversed(rows)
    ]


async def add_observation(
    patient_id: str,
    label: str,
    value: str,
    unit: str | None,
    observation_date: str | None,
    source_document_id: str,
    abnormal_flag: str | None = None,
) -> str:
    """Add a clinical observation. Observations always append."""
    del abnormal_flag
    tenant_id = _tenant_id()
    numeric_value = _to_decimal(value)
    row = Observation(
        tenant_id=tenant_id,
        patient_id=_as_uuid(patient_id),
        label=str(label),
        value_numeric=numeric_value,
        value_text=None if numeric_value is not None else str(value),
        unit=unit or None,
        effective_date=_parse_observation_date(observation_date),
        source_document_id=_as_uuid(source_document_id),
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
        return str(row.id)


async def add_medication(
    patient_id: str,
    name: str,
    dose: str | None,
    frequency: str | None,
    route: str | None,
    status: str,
    source_document_id: str,
) -> str:
    """Add a medication entry."""
    row = Medication(
        tenant_id=_tenant_id(),
        patient_id=_as_uuid(patient_id),
        name=str(name),
        dose=dose or None,
        frequency=frequency or None,
        route=route or None,
        status=_normalise_status(status),
        source_document_id=_as_uuid(source_document_id),
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
        return str(row.id)


async def update_medication_status(
    patient_id: str,
    medication_name: str,
    new_status: str,
    source_document_id: str,
) -> str:
    """Update the best matching active medication's status."""
    tenant_id = _tenant_id()
    pid = _as_uuid(patient_id)
    async with SessionLocal() as session:
        med = (
            await session.execute(
                select(Medication).where(
                    Medication.tenant_id == tenant_id,
                    Medication.patient_id == pid,
                    func.lower(Medication.name) == medication_name.lower(),
                    Medication.status == "active",
                )
            )
        ).scalars().first()
        if med is None:
            return await add_medication(patient_id, medication_name, None, None, None, new_status, source_document_id)
        med.status = _normalise_status(new_status)
        await session.commit()
        return str(med.id)


async def add_problem(
    patient_id: str,
    label: str,
    status: str,
    icd10_hint: str | None,
    source_document_id: str,
) -> str:
    """Add a diagnosis or problem."""
    row = Problem(
        tenant_id=_tenant_id(),
        patient_id=_as_uuid(patient_id),
        label=str(label),
        status=_normalise_problem_status(status),
        icd10_code=icd10_hint or None,
        source_document_id=_as_uuid(source_document_id),
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
        return str(row.id)


async def add_allergy(
    patient_id: str,
    substance: str,
    reaction: str | None,
    severity: str | None,
    source_document_id: str,
) -> str:
    """Add an allergy entry."""
    row = Allergy(
        tenant_id=_tenant_id(),
        patient_id=_as_uuid(patient_id),
        substance=str(substance),
        reaction=reaction or None,
        severity=severity or None,
        source_document_id=_as_uuid(source_document_id),
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
        return str(row.id)


async def raise_flag(
    patient_id: str,
    document_id: str,
    field: str,
    current_value: str,
    new_value: str,
    severity: str,
    reasoning: str,
    resource_type: str = "patient_profile",
    details: dict[str, Any] | None = None,
) -> str:
    """Raise a reconciliation flag for human review."""
    severity = severity if severity in {"critical", "warning", "info"} else "warning"
    flag_details = details or {
        "field": field,
        "existing_value": current_value or None,
        "document_value": new_value,
        "review_required": True,
    }
    row = ReconcileFlag(
        tenant_id=_tenant_id(),
        patient_id=_as_uuid(patient_id),
        document_id=_as_uuid(document_id),
        kind="conflict" if current_value else "new_data",
        resource_type=resource_type,
        existing_id=None,
        new_extraction_id=None,
        details=flag_details,
        severity=severity,
        tier=2,
        agent_reasoning=reasoning,
        resolution_options=["keep_existing", "use_new"],
    )
    async with SessionLocal() as session:
        document = await session.get(Document, row.document_id)
        if document is None or document.tenant_id != row.tenant_id:
            raise ValueError("document not found for tenant")
        session.add(row)
        await session.commit()
        return str(row.id)


async def load_pending_flags(document_id: str) -> list[dict]:
    tenant_id = _tenant_id()
    did = _as_uuid(document_id)
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ReconcileFlag)
                .where(
                    ReconcileFlag.tenant_id == tenant_id,
                    ReconcileFlag.document_id == did,
                    ReconcileFlag.resolved.is_(False),
                )
                .order_by(ReconcileFlag.created_at.desc())
            )
        ).scalars().all()
    return [
        {
            "flag_id": str(row.id),
            "field": str(row.details.get("field") or row.resource_type),
            "current_value": str(row.details.get("existing_value") or row.details.get("existing") or ""),
            "new_value": str(row.details.get("document_value") or row.details.get("new") or ""),
            "severity": row.severity,
            "reasoning": row.agent_reasoning or "",
        }
        for row in rows
    ]


def _normalise_status(status: str | None) -> str:
    value = _normalise(status)
    if value in {"inactive", "stopped", "stop", "ceased"}:
        return "discontinued"
    if value in {"held", "hold"}:
        return "held"
    if value in {"historical", "planned", "discontinued"}:
        return value
    return "active"


def _normalise_problem_status(status: str | None) -> str:
    value = _normalise(status)
    if value in {"resolved", "historical"}:
        return value
    return "active"
