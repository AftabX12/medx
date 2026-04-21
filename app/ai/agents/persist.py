"""Persist extracted payloads to typed clinical rows + an Extraction audit row.

Reconciliation (duplicate/conflict detection) runs alongside persistence and writes
to `reconcile_flags`. Existing rows are never overwritten — v1 ethos.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.doctype import DocType
from app.db.models import (
    Allergy,
    Extraction,
    Medication,
    Observation,
    Problem,
    ReconcileFlag,
)
from app.db.repositories.allergy import AllergyRepository
from app.db.repositories.extraction import ExtractionRepository
from app.db.repositories.medication import MedicationRepository
from app.db.repositories.observation import ObservationRepository
from app.db.repositories.problem import ProblemRepository
from app.logging import get_logger

log = get_logger(__name__)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(str(value)), datetime.min.time())
        except ValueError:
            return None


async def _write_audit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    doc_type: DocType,
    payload: dict,
    model: str | None,
) -> Extraction:
    ext = Extraction(
        tenant_id=tenant_id,
        document_id=document_id,
        field_type=doc_type.value,
        value_raw=None,
        value_normalized=payload,
        confidence=None,
        extracted_by_model=model,
    )
    await ExtractionRepository(session, tenant_id).add(ext)
    return ext


async def _flag(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    extraction_id: uuid.UUID,
    kind: str,
    resource_type: str,
    existing_id: uuid.UUID | None,
    details: dict,
) -> None:
    flag = ReconcileFlag(
        tenant_id=tenant_id,
        patient_id=patient_id,
        document_id=document_id,
        kind=kind,
        resource_type=resource_type,
        existing_id=existing_id,
        new_extraction_id=extraction_id,
        details=details,
    )
    session.add(flag)
    await session.flush()


async def _persist_lab(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: dict,
) -> None:
    collection_dt = _parse_datetime(payload.get("collection_date"))
    repo = ObservationRepository(session, tenant_id)
    for obs in payload.get("observations", []) or []:
        label = (obs.get("label") or "").strip()
        if not label:
            continue
        value = obs.get("value")
        val_num = _to_decimal(value)
        row = Observation(
            tenant_id=tenant_id,
            patient_id=patient_id,
            loinc_code=(obs.get("loinc_hint") or None),
            label=label,
            value_numeric=val_num,
            value_text=None if val_num is not None else (str(value) if value is not None else None),
            unit=obs.get("unit"),
            effective_date=collection_dt,
            source_document_id=document_id,
        )
        await repo.add(row)


async def _persist_imaging(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: dict,
) -> None:
    study_dt = _parse_datetime(payload.get("study_date"))
    repo = ObservationRepository(session, tenant_id)
    modality = payload.get("modality") or "imaging"
    for meas in payload.get("measurements", []) or []:
        label = (meas.get("label") or "").strip()
        if not label:
            continue
        val_num = _to_decimal(meas.get("value"))
        row = Observation(
            tenant_id=tenant_id,
            patient_id=patient_id,
            loinc_code=(meas.get("loinc_hint") or None),
            label=f"{modality}: {label}" if modality else label,
            value_numeric=val_num,
            value_text=None if val_num is not None else str(meas.get("value")),
            unit=meas.get("unit"),
            effective_date=study_dt,
            source_document_id=document_id,
        )
        await repo.add(row)


async def _persist_meds(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    extraction_id: uuid.UUID,
    meds: list[dict],
) -> None:
    repo = MedicationRepository(session, tenant_id)
    for med in meds or []:
        name = (med.get("name") or "").strip()
        if not name:
            continue
        existing = await repo.find_active_by_name(patient_id, name)
        dose = med.get("dose")
        freq = med.get("frequency")
        route = med.get("route")
        status = (med.get("status") or "active").lower()

        if existing is not None:
            if (existing.dose or "") == (dose or "") and (existing.frequency or "") == (freq or ""):
                await _flag(
                    session,
                    tenant_id=tenant_id,
                    patient_id=patient_id,
                    document_id=document_id,
                    extraction_id=extraction_id,
                    kind="duplicate",
                    resource_type="medication",
                    existing_id=existing.id,
                    details={"name": name, "dose": dose, "frequency": freq},
                )
                continue
            await _flag(
                session,
                tenant_id=tenant_id,
                patient_id=patient_id,
                document_id=document_id,
                extraction_id=extraction_id,
                kind="conflict",
                resource_type="medication",
                existing_id=existing.id,
                details={
                    "name": name,
                    "existing": {"dose": existing.dose, "frequency": existing.frequency},
                    "new": {"dose": dose, "frequency": freq},
                },
            )

        row = Medication(
            tenant_id=tenant_id,
            patient_id=patient_id,
            rxnorm_code=(med.get("rxnorm_hint") or None),
            name=name,
            dose=dose,
            frequency=freq,
            route=route,
            status=status,
            source_document_id=document_id,
        )
        await repo.add(row)


async def _persist_problems(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    extraction_id: uuid.UUID,
    diagnoses: list[dict],
) -> None:
    repo = ProblemRepository(session, tenant_id)
    for dx in diagnoses or []:
        label = (dx.get("label") or "").strip()
        if not label:
            continue
        existing = await repo.find_by_label(patient_id, label)
        if existing is not None:
            await _flag(
                session,
                tenant_id=tenant_id,
                patient_id=patient_id,
                document_id=document_id,
                extraction_id=extraction_id,
                kind="duplicate",
                resource_type="problem",
                existing_id=existing.id,
                details={"label": label},
            )
            continue
        row = Problem(
            tenant_id=tenant_id,
            patient_id=patient_id,
            icd10_code=(dx.get("icd10_hint") or None),
            label=label,
            status=(dx.get("status") or "active").lower(),
            source_document_id=document_id,
        )
        await repo.add(row)


async def _persist_allergies(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    extraction_id: uuid.UUID,
    allergies: list[dict],
) -> None:
    repo = AllergyRepository(session, tenant_id)
    for alg in allergies or []:
        substance = (alg.get("substance") or "").strip()
        if not substance:
            continue
        existing = await repo.find_by_substance(patient_id, substance)
        if existing is not None:
            await _flag(
                session,
                tenant_id=tenant_id,
                patient_id=patient_id,
                document_id=document_id,
                extraction_id=extraction_id,
                kind="duplicate",
                resource_type="allergy",
                existing_id=existing.id,
                details={"substance": substance},
            )
            continue
        row = Allergy(
            tenant_id=tenant_id,
            patient_id=patient_id,
            substance=substance,
            reaction=alg.get("reaction"),
            severity=alg.get("severity"),
            source_document_id=document_id,
        )
        session.add(row)
        await session.flush()


async def _persist_hp(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    extraction_id: uuid.UUID,
    payload: dict,
) -> None:
    visit_dt = _parse_datetime(payload.get("visit_date"))
    obs_repo = ObservationRepository(session, tenant_id)

    # Vital signs → Observation
    for vs in payload.get("vital_signs", []) or []:
        label = (vs.get("label") or "").strip()
        if not label:
            continue
        value = vs.get("value")
        if value is None:
            continue
        val_num = _to_decimal(value)
        row = Observation(
            tenant_id=tenant_id,
            patient_id=patient_id,
            label=label,
            value_numeric=val_num,
            value_text=None if val_num is not None else (str(value) if value is not None else None),
            unit=vs.get("unit"),
            effective_date=visit_dt,
            source_document_id=document_id,
        )
        await obs_repo.add(row)

    # Problems
    await _persist_problems(
        session,
        tenant_id=tenant_id,
        patient_id=patient_id,
        document_id=document_id,
        extraction_id=extraction_id,
        diagnoses=payload.get("problems", []) or [],
    )

    # Medications
    await _persist_meds(
        session,
        tenant_id=tenant_id,
        patient_id=patient_id,
        document_id=document_id,
        extraction_id=extraction_id,
        meds=payload.get("medications", []) or [],
    )

    # Allergies
    await _persist_allergies(
        session,
        tenant_id=tenant_id,
        patient_id=patient_id,
        document_id=document_id,
        extraction_id=extraction_id,
        allergies=payload.get("allergies", []) or [],
    )

    # Update patient chief_complaint if not already set
    if payload.get("chief_complaint"):
        from app.db.models import Patient
        from sqlalchemy import select as sa_select
        result = await session.execute(
            sa_select(Patient).where(Patient.id == patient_id)
        )
        patient = result.scalars().first()
        if patient and not patient.chief_complaint:
            patient.chief_complaint = payload["chief_complaint"]
            await session.flush()


async def _persist_discharge(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    extraction_id: uuid.UUID,
    payload: dict,
) -> None:
    await _persist_problems(
        session,
        tenant_id=tenant_id,
        patient_id=patient_id,
        document_id=document_id,
        extraction_id=extraction_id,
        diagnoses=payload.get("diagnoses", []) or [],
    )
    await _persist_meds(
        session,
        tenant_id=tenant_id,
        patient_id=patient_id,
        document_id=document_id,
        extraction_id=extraction_id,
        meds=payload.get("medications", []) or [],
    )
    discharge_dt = _parse_datetime(payload.get("discharge_date"))
    repo = ObservationRepository(session, tenant_id)
    for obs in payload.get("observations", []) or []:
        label = (obs.get("label") or "").strip()
        if not label:
            continue
        val_num = _to_decimal(obs.get("value"))
        row = Observation(
            tenant_id=tenant_id,
            patient_id=patient_id,
            loinc_code=(obs.get("loinc_hint") or None),
            label=label,
            value_numeric=val_num,
            value_text=None if val_num is not None else str(obs.get("value")),
            unit=obs.get("unit"),
            effective_date=discharge_dt,
            source_document_id=document_id,
        )
        await repo.add(row)


async def persist_dynamic_extraction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    doc_type_label: str,
    payload: dict,
    model: str | None,
) -> Extraction:
    """Write an audit row for a dynamically-typed document.

    No clinical table writes — payload is stored as-is in value_normalized (JSONB).
    Used by the Tier 3 dynamic fallback path in router.py.
    """
    ext = Extraction(
        tenant_id=tenant_id,
        document_id=document_id,
        field_type=doc_type_label,
        value_raw=None,
        value_normalized=payload,
        confidence=None,
        extracted_by_model=model,
    )
    await ExtractionRepository(session, tenant_id).add(ext)
    return ext


async def persist_extraction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    doc_type: DocType,
    payload: dict,
    model: str | None,
) -> Extraction:
    ext = await _write_audit(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        doc_type=doc_type,
        payload=payload,
        model=model,
    )

    if doc_type == DocType.LAB_PANEL:
        await _persist_lab(
            session,
            tenant_id=tenant_id,
            patient_id=patient_id,
            document_id=document_id,
            payload=payload,
        )
    elif doc_type == DocType.IMAGING_REPORT:
        await _persist_imaging(
            session,
            tenant_id=tenant_id,
            patient_id=patient_id,
            document_id=document_id,
            payload=payload,
        )
    elif doc_type == DocType.MED_LIST:
        await _persist_meds(
            session,
            tenant_id=tenant_id,
            patient_id=patient_id,
            document_id=document_id,
            extraction_id=ext.id,
            meds=payload.get("medications", []) or [],
        )
    elif doc_type == DocType.DISCHARGE_SUMMARY:
        await _persist_discharge(
            session,
            tenant_id=tenant_id,
            patient_id=patient_id,
            document_id=document_id,
            extraction_id=ext.id,
            payload=payload,
        )
    elif doc_type == DocType.HISTORY_PHYSICAL:
        await _persist_hp(
            session,
            tenant_id=tenant_id,
            patient_id=patient_id,
            document_id=document_id,
            extraction_id=ext.id,
            payload=payload,
        )
    else:
        log.info("persist_skipped_doc_type", doc_type=doc_type.value)

    return ext
