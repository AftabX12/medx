"""Pipeline orchestrator: classify → extract → persist → profile → summarize.

This module is the entry point for the `extract_document` queue job. It runs
the full 6-step AI pipeline for a single document and emits real-time step
events via the EventBus so the browser can update without polling.

Step ordering and skip logic:
  1. classify  — skip if doc.doc_type already set (e.g. re-extract run)
  2. extract   — two paths:
       - known type (lab, imaging, discharge, med_list, h&p): static prompt + schema → typed DB rows
       - unknown type (other): dynamic plan+extract → JSONB audit row only, doc_type updated to
         LLM-generated label (e.g. "pharmacy_receipt")
  3. persist   — typed rows for known types; JSONB-only for dynamic types
  4. profile   — auto-fill patient demographics; always runs for all doc types
  5. summarize — regenerates patient.ai_summary from all current clinical data

Steps 2 (extract) and 4 (profile/patient-info fetch) run in parallel via
asyncio.gather to minimize wall-clock time. Steps 3 and 5 are sequential
because they depend on the results of the preceding steps.

A failed step emits a "failed" event and returns early; profile and summarize
failures are non-fatal (logged as warnings, pipeline continues).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from app.ai.agents.classify import classify_document
from app.ai.agents.doctype import DocType
from app.ai.agents.extract import extract_document, supported_doc_types
from app.ai.agents.extract_patient_info import extract_patient_info
from app.ai.agents.persist import persist_dynamic_extraction, persist_extraction
from app.ai.agents.plan_extract import plan_and_extract
from app.ai.agents.profile_reconcile import reconcile_patient_profile
from app.ai.agents.summarize import summarize_patient
from app.ai.client import llm_log_document_id, llm_log_tenant_id
from app.ai.models import ModelRole, resolve_model
from app.config import get_settings
from app.db.models import Document, Patient
from app.events import get_event_bus
from app.validation import validate_extraction_output
from app.db.session import SessionLocal
from app.logging import get_logger

log = get_logger(__name__)


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string for pipeline_status timestamps."""
    return datetime.now(timezone.utc).isoformat()


async def _set_step(session, doc: Document, step: str, status: str, detail: str = "") -> None:
    """Update a pipeline step's status in pipeline_status and emit an SSE event.

    Writes to pipeline_status JSON column and flushes immediately so the DB
    reflects the current state even before the outer transaction commits.
    Also emits to the EventBus so connected browser tabs see the update in real time.
    """
    ps = dict(doc.pipeline_status or {})
    ps[step] = {"status": status, "ts": _now(), "detail": detail}
    doc.pipeline_status = ps
    await session.flush()
    log.info("pipeline_step", document_id=str(doc.id), step=step, status=status, detail=detail)
    await get_event_bus().emit(doc.id, {"type": "step", "step": step, "status": status, "detail": detail})


async def run_extraction(document_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Run the full AI extraction pipeline for a document.

    Entry point called by the queue worker for the `extract_document` job.
    Verifies tenant ownership before processing — a document can only be
    extracted by a worker running in the correct tenant context.
    """
    settings = get_settings()
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None or doc.tenant_id != tenant_id:
            return

        patient = await session.get(Patient, doc.patient_id)
        if patient is None or patient.tenant_id != tenant_id:
            log.warning(
                "extraction_blocked_tenant_mismatch",
                document_id=str(document_id),
                tenant_id=str(tenant_id),
            )
            return

        # Set context vars for LLM call logging (Phase 4c)
        llm_log_tenant_id.set(tenant_id)
        llm_log_document_id.set(document_id)

        text = doc.ocr_text or ""
        if not text.strip():
            await _set_step(session, doc, "classify", "skipped", "no OCR text")
            await session.commit()
            return

        # Cap text sent to LLM — beyond ~10k chars the model sees diminishing returns
        # and inference time grows linearly with input length.
        text_for_llm = text[:10000]
        extraction = None
        extracted_profile = None

        # --- Classify (skip if doc_type already known, e.g. re-extract) ---
        if doc.doc_type:
            try:
                doc_type = DocType(doc.doc_type)
                await _set_step(session, doc, "classify", "ok", f"{doc_type.value} (cached)")
                await session.commit()
            except ValueError:
                doc_type = None
        else:
            doc_type = None

        if doc_type is None:
            await _set_step(session, doc, "classify", "running")
            await session.commit()
            try:
                doc_type, confidence = await classify_document(text_for_llm)
                doc.doc_type = doc_type.value
                await _set_step(session, doc, "classify", "ok", f"{doc_type.value} ({confidence:.0%})")
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                await _set_step(session, doc, "classify", "failed", str(exc))
                await session.commit()
                log.warning("classify_failed", document_id=str(document_id), error=str(exc))
                return

        has_extractor = doc_type in supported_doc_types()
        if not has_extractor:
            # --- Tier 3 dynamic fallback: plan + extract for unrecognized doc types ---
            # Replaces the old "skip" behavior. The LLM self-generates an extraction
            # prompt, pulls structured data, and we store it as JSONB (no clinical rows).
            await _set_step(session, doc, "extract", "running")
            await _set_step(session, doc, "profile", "running")
            await session.commit()
            dynamic_label = None
            try:
                dyn_task = asyncio.create_task(plan_and_extract(text_for_llm))
                patient_info_task = asyncio.create_task(extract_patient_info(text_for_llm))
                (dynamic_label, dyn_payload), extracted_profile = await asyncio.gather(
                    dyn_task, patient_info_task
                )
                # Update doc_type to the LLM-generated label (more specific than "other")
                doc.doc_type = dynamic_label
                await _set_step(session, doc, "extract", "ok", dynamic_label)
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                await _set_step(session, doc, "extract", "failed", str(exc))
                await session.commit()
                log.warning("dynamic_extract_failed", document_id=str(document_id), error=str(exc))
                extracted_profile = None

            # Persist dynamic extraction as audit-only JSONB row (non-fatal)
            if dynamic_label is not None:
                await _set_step(session, doc, "persist", "running")
                await session.commit()
                try:
                    model_name = resolve_model(ModelRole.EXTRACT, settings)
                    extraction = await persist_dynamic_extraction(
                        session,
                        tenant_id=tenant_id,
                        document_id=document_id,
                        doc_type_label=dynamic_label,
                        payload=dyn_payload,
                        model=model_name,
                    )
                    await _set_step(session, doc, "persist", "ok")
                    await session.commit()
                except Exception as exc:  # noqa: BLE001
                    await _set_step(session, doc, "persist", "failed", str(exc))
                    await session.commit()
                    log.warning("dynamic_persist_failed", document_id=str(document_id), error=str(exc))
        else:
            # --- Extract + patient-info in parallel (independent LLM calls) ---
            await _set_step(session, doc, "extract", "running")
            await _set_step(session, doc, "profile", "running")
            await session.commit()
            try:
                extract_task = asyncio.create_task(extract_document(doc_type, text_for_llm))
                patient_info_task = asyncio.create_task(extract_patient_info(text_for_llm))
                payload, extracted_profile = await asyncio.gather(extract_task, patient_info_task)
                validate_extraction_output(doc_type.value, payload)
                await _set_step(session, doc, "extract", "ok")
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                await _set_step(session, doc, "extract", "failed", str(exc))
                await session.commit()
                log.warning("extract_failed", document_id=str(document_id), error=str(exc))
                return

            # --- Persist ---
            await _set_step(session, doc, "persist", "running")
            await session.commit()
            try:
                model_name = resolve_model(ModelRole.EXTRACT, settings)
                extraction = await persist_extraction(
                    session,
                    tenant_id=tenant_id,
                    patient_id=doc.patient_id,
                    document_id=document_id,
                    doc_type=doc_type,
                    payload=payload,
                    model=model_name,
                )
                await _set_step(session, doc, "persist", "ok")
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                await _set_step(session, doc, "persist", "failed", str(exc))
                await session.commit()
                log.warning("persist_failed", document_id=str(document_id), error=str(exc))
                return

        # --- Profile reconcile (patient_info already fetched in parallel above) ---
        if extracted_profile is None and not has_extractor:
            # Dynamic path ran patient_info in parallel but it failed; retry serially
            await _set_step(session, doc, "profile", "running")
            await session.commit()
            try:
                extracted_profile = await extract_patient_info(text_for_llm)
            except Exception as exc:  # noqa: BLE001
                log.warning("patient_info_failed", document_id=str(document_id), error=str(exc))

        try:
            extraction_id = extraction.id if extraction is not None else None
            n_flags = await reconcile_patient_profile(
                session,
                tenant_id=tenant_id,
                patient_id=doc.patient_id,
                document_id=document_id,
                extraction_id=extraction_id,
                extracted=extracted_profile,
            )
            detail = f"auto-filled fields; {n_flags} conflict(s) flagged" if extracted_profile else "no patient info found"
            await _set_step(session, doc, "profile", "ok", detail)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await _set_step(session, doc, "profile", "failed", str(exc))
            await session.commit()
            log.warning("profile_reconcile_failed", document_id=str(document_id), error=str(exc))
            # Non-fatal — continue to summarize

        # --- Summarize patient ---
        await _set_step(session, doc, "summarize", "running")
        await session.commit()
        try:
            from sqlalchemy import select
            from app.db.models import Medication, Observation, Problem

            patient = await session.get(Patient, doc.patient_id)
            obs_rows = (
                await session.execute(
                    select(Observation)
                    .where(Observation.patient_id == doc.patient_id)
                    .order_by(Observation.created_at.desc())
                    .limit(20)
                )
            ).scalars().all()
            med_rows = (
                await session.execute(
                    select(Medication)
                    .where(
                        Medication.patient_id == doc.patient_id,
                        Medication.status == "active",
                    )
                    .limit(20)
                )
            ).scalars().all()
            prob_rows = (
                await session.execute(
                    select(Problem)
                    .where(
                        Problem.patient_id == doc.patient_id,
                        Problem.status == "active",
                    )
                    .limit(20)
                )
            ).scalars().all()

            context = {
                "patient": {
                    "name": f"{patient.given_name} {patient.family_name}" if patient else "unknown",
                    "dob": str(patient.date_of_birth) if patient and patient.date_of_birth else None,
                    "sex": patient.sex if patient else None,
                    "chief_complaint": patient.chief_complaint if patient else None,
                },
                "active_problems": [p.label for p in prob_rows],
                "active_medications": [
                    {"name": m.name, "dose": m.dose, "frequency": m.frequency}
                    for m in med_rows
                ],
                "recent_observations": [
                    {"label": o.label, "value": str(o.value_numeric or o.value_text), "unit": o.unit}
                    for o in obs_rows
                ],
            }
            summary = await summarize_patient(context)
            if patient and summary:
                patient.ai_summary = summary
            await _set_step(session, doc, "summarize", "ok")
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await _set_step(session, doc, "summarize", "failed", str(exc))
            await session.commit()
            log.warning("summarize_failed", document_id=str(document_id), error=str(exc))

    await get_event_bus().emit(document_id, {"type": "done"})
