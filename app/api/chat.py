"""Chat endpoint: doctor asks questions about their patients and EHR data."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter
from sqlalchemy import func, select

from app.ai.agents.chat import chat_answer
from app.ai.errors import RateLimitExhausted
from app.db.models import Document, Medication, Observation, Patient, Problem
from app.deps import CurrentUser, SessionDep

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    patient_id: str | None = None


class ChatResponse(BaseModel):
    answer: str


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, session: SessionDep, user: CurrentUser) -> ChatResponse:
    """Answer a clinical question using the tenant's patient and document data as context.

    If `patient_id` is provided, context is scoped to that one patient.
    Otherwise, up to 100 patients' summarised data is included.
    """
    tid = user.tenant_id

    # ── Patient query ─────────────────────────────────────────────────────────
    if body.patient_id:
        import uuid as _uuid
        try:
            pid = _uuid.UUID(body.patient_id)
        except ValueError:
            pid = None
        patients_q = (
            select(Patient).where(Patient.tenant_id == tid, Patient.id == pid).limit(1)
            if pid else None
        )
    else:
        patients_q = select(Patient).where(Patient.tenant_id == tid).limit(100)

    patients = (
        (await session.execute(patients_q)).scalars().all()
        if patients_q is not None else []
    )

    # ── Document summary ──────────────────────────────────────────────────────
    doc_counts = (await session.execute(
        select(Document.ocr_status, func.count().label("n"))
        .where(Document.tenant_id == tid)
        .group_by(Document.ocr_status)
    )).all()
    doc_summary = {row.ocr_status: row.n for row in doc_counts}
    total_docs = sum(doc_summary.values())

    # ── Per-patient clinical data ─────────────────────────────────────────────
    patient_list = []
    for p in patients:
        obs = (await session.execute(
            select(Observation).where(Observation.patient_id == p.id).limit(50)
        )).scalars().all()
        meds = (await session.execute(
            select(Medication).where(Medication.patient_id == p.id).limit(30)
        )).scalars().all()
        probs = (await session.execute(
            select(Problem).where(Problem.patient_id == p.id).limit(30)
        )).scalars().all()
        docs = (await session.execute(
            select(Document.original_filename, Document.doc_type, Document.ocr_status)
            .where(Document.patient_id == p.id)
        )).all()

        patient_list.append({
            "name": f"{p.given_name} {p.family_name}",
            "mrn": p.mrn,
            "dob": str(p.date_of_birth) if p.date_of_birth else None,
            "sex": p.sex,
            "blood_type": p.blood_type,
            "chief_complaint": p.chief_complaint,
            "primary_physician": p.primary_physician,
            "phone": p.phone,
            "email": p.email,
            "insurance": p.insurance_provider,
            "ai_summary": p.ai_summary,
            "problems": [{"label": pr.label, "status": pr.status} for pr in probs],
            "medications": [
                {"name": m.name, "dose": m.dose, "frequency": m.frequency, "status": m.status}
                for m in meds
            ],
            "observations": [
                {"label": o.label, "value": str(o.value_numeric or o.value_text), "unit": o.unit}
                for o in obs
            ],
            "documents": [
                {"filename": d.original_filename, "type": d.doc_type, "status": d.ocr_status}
                for d in docs
            ],
        })

    context: dict = {
        "total_patients": len(patients),
        "total_documents": total_docs,
        "document_status_breakdown": doc_summary,
        "patients": patient_list,
    }

    try:
        answer = await chat_answer(body.question, context)
    except RateLimitExhausted:
        answer = "The AI provider is rate-limited right now. Please wait a minute and try again."
    except Exception:
        answer = "An error occurred while generating a response. Please try again."
    return ChatResponse(answer=answer)
