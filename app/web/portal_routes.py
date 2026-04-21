"""Patient self-service portal — routes under /portal/* and /patient/*.

Two routers are registered in main.py:
  router        (prefix /portal)  — all portal functionality
  patient_router (prefix /patient) — canonical auth URLs (/patient/login,
                                     /patient/register) that delegate to the
                                     same handlers as /portal/login|register

Auth: patients authenticate with email + password (no tenant name needed).
      The JWT is stored in the same SESSION_COOKIE used by the doctor UI.

Route groups:
  Auth      — register, login, logout
  Dashboard — /portal/dashboard (summary + upcoming)
  Records   — /portal/records (full clinical history read-only)
  Documents — /portal/documents (upload + list)
  Appointments — /portal/appointments (book + cancel)
  Messages  — /portal/messages (patient ↔ doctor)
  Chat      — /portal/chat (AI assistant, context-scoped to patient's data)
  Doctor-side — /portal/doctor/messages/{patient_id}/reply,
                /portal/doctor/appointments/{id}/confirm|cancel
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

# /patient/* aliases for the canonical login/register URLs
patient_router = APIRouter(prefix="/patient", tags=["portal"])

from app.db.models import (
    Allergy,
    Appointment,
    Document,
    Medication,
    Message,
    Observation,
    Patient,
    Problem,
    User,
)
from app.db.repositories.document import DocumentRepository
from app.db.repositories.extraction import ExtractionRepository
from app.db.repositories.patient import PatientRepository
from app.deps import SESSION_COOKIE, PatientUser, SessionDep, get_optional_user
from app.ingestion.store import get_document_store
from app.logging import get_logger
from app.queue import get_queue
from app.security import create_access_token, hash_password, verify_password
from app.validation import UploadRejected, validate_upload
from app.web.templates import templates

log = get_logger(__name__)
router = APIRouter(prefix="/portal", tags=["portal"])

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _render(request: Request, user: User | None, template: str, **ctx):
    """Render a portal Jinja2 template with `current_user` injected."""
    return templates.TemplateResponse(
        request, template, {"current_user": user, **ctx}
    )


def _set_session(response: RedirectResponse, token: str) -> None:
    """Write the JWT to the httponly session cookie on a redirect response."""
    from app.config import get_settings
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.app_env != "dev",
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )


# ──────────────────────────────────────────────
# Auth
# ──────────────────────────────────────────────

@router.get("/register")
async def portal_register_page(request: Request, session: SessionDep):
    """Render the patient self-registration page."""
    user = await get_optional_user(request, session)
    if user and user.role == "patient":
        return RedirectResponse("/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, None, "portal/register.html", error=None)


@router.post("/register")
async def portal_register(
    request: Request,
    session: SessionDep,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
):
    """Patient self-registration.

    Looks for an existing Patient with matching email inside every tenant.
    If found → links. If not found → creates a new stub Patient record.
    Always creates a new User(role='patient') under that tenant.
    """
    from app.db.repositories.tenant import TenantRepository

    email = email.strip().lower()

    # Check if a user account already exists for this email across all tenants
    existing_user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing_user:
        return _render(request, None, "portal/register.html",
                       error="An account with this email already exists. Please log in.")

    # Find a Patient record with matching email (any tenant)
    patient = (
        await session.execute(select(Patient).where(Patient.email == email))
    ).scalar_one_or_none()

    if patient:
        tenant_id = patient.tenant_id
    else:
        # Create a new tenant for this patient (standalone patient scenario)
        from app.db.models import Tenant
        tenant = Tenant(name=f"patient-{email}")
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id

        # Stub Patient record — name filled from full_name until doctor completes it
        name_parts = full_name.strip().split(" ", 1)
        given = name_parts[0] if name_parts else email.split("@")[0]
        family = name_parts[1] if len(name_parts) > 1 else ""
        import random, string
        mrn = "P" + "".join(random.choices(string.digits, k=8))
        patient = Patient(
            tenant_id=tenant_id,
            mrn=mrn,
            given_name=given,
            family_name=family,
            email=email,
        )
        session.add(patient)
        await session.flush()

    user = User(
        tenant_id=tenant_id,
        email=email,
        full_name=full_name.strip() or None,
        password_hash=hash_password(password),
        role="patient",
        patient_id=patient.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id)
    resp = RedirectResponse("/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    _set_session(resp, token)
    return resp


@router.get("/login")
async def portal_login_page(request: Request, session: SessionDep):
    """Render the patient login page."""
    user = await get_optional_user(request, session)
    if user and user.role == "patient":
        return RedirectResponse("/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, None, "portal/login.html", error=None)


@router.post("/login")
async def portal_login(  # noqa: D401
    request: Request,
    session: SessionDep,
    email: str = Form(...),
    password: str = Form(...),
):
    email = email.strip().lower()
    user = (
        await session.execute(
            select(User).where(User.email == email, User.role == "patient", User.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return _render(request, None, "portal/login.html", error="Invalid email or password.")
    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id)
    resp = RedirectResponse("/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    _set_session(resp, token)
    return resp


@router.post("/logout")
async def portal_logout():
    """Clear the session cookie and redirect to the patient login page."""
    resp = RedirectResponse("/portal/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# ──────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────

@router.get("/")
async def portal_root(user: PatientUser):
    return RedirectResponse("/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/dashboard")
async def portal_dashboard(request: Request, session: SessionDep, user: PatientUser):
    """Patient home: AI summary, active conditions, current meds, recent labs, upcoming appointments."""
    patient_id = user.patient_id
    patient = await session.get(Patient, patient_id)

    problems = (
        await session.execute(
            select(Problem)
            .where(Problem.patient_id == patient_id, Problem.status == "active")
            .order_by(Problem.created_at.desc())
            .limit(5)
        )
    ).scalars().all()

    meds = (
        await session.execute(
            select(Medication)
            .where(Medication.patient_id == patient_id, Medication.status == "active")
            .order_by(Medication.created_at.desc())
            .limit(5)
        )
    ).scalars().all()

    recent_obs = (
        await session.execute(
            select(Observation)
            .where(Observation.patient_id == patient_id)
            .order_by(Observation.effective_date.desc().nullslast(), Observation.created_at.desc())
            .limit(6)
        )
    ).scalars().all()

    upcoming_appts = (
        await session.execute(
            select(Appointment)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.scheduled_at >= datetime.now(timezone.utc),
                Appointment.status.in_(["pending", "confirmed"]),
            )
            .order_by(Appointment.scheduled_at)
            .limit(3)
        )
    ).scalars().all()

    unread_count = (
        await session.execute(
            select(Message)
            .where(
                Message.patient_id == patient_id,
                Message.direction == "doctor_to_patient",
                Message.read_at.is_(None),
            )
        )
    ).scalars().all()

    return _render(
        request, user, "portal/dashboard.html",
        patient=patient,
        problems=problems,
        meds=meds,
        recent_obs=recent_obs,
        upcoming_appts=upcoming_appts,
        unread_count=len(unread_count),
    )


# ──────────────────────────────────────────────
# Health Records
# ──────────────────────────────────────────────

@router.get("/records")
async def portal_records(request: Request, session: SessionDep, user: PatientUser):
    """Full health record view: problems, medications, observations, allergies (read-only)."""
    patient_id = user.patient_id
    patient = await session.get(Patient, patient_id)

    problems = (
        await session.execute(
            select(Problem)
            .where(Problem.patient_id == patient_id)
            .order_by(Problem.status, Problem.created_at.desc())
        )
    ).scalars().all()

    meds = (
        await session.execute(
            select(Medication)
            .where(Medication.patient_id == patient_id)
            .order_by(Medication.status, Medication.name)
        )
    ).scalars().all()

    observations = (
        await session.execute(
            select(Observation)
            .where(Observation.patient_id == patient_id)
            .order_by(Observation.effective_date.desc().nullslast(), Observation.created_at.desc())
        )
    ).scalars().all()

    allergies = (
        await session.execute(
            select(Allergy).where(Allergy.patient_id == patient_id)
        )
    ).scalars().all()

    return _render(
        request, user, "portal/records.html",
        patient=patient,
        problems=problems,
        meds=meds,
        observations=observations,
        allergies=allergies,
    )


# ──────────────────────────────────────────────
# Documents
# ──────────────────────────────────────────────

@router.get("/documents")
async def portal_documents(request: Request, session: SessionDep, user: PatientUser):
    """List all documents uploaded by or for this patient."""
    patient_id = user.patient_id
    patient = await session.get(Patient, patient_id)
    docs = await DocumentRepository(session, user.tenant_id).list_for_patient(patient_id)
    return _render(request, user, "portal/documents.html", patient=patient, documents=docs, error=None)


@router.post("/documents")
async def portal_upload_document(  # noqa: D401
    request: Request,
    session: SessionDep,
    user: PatientUser,
    file: UploadFile = File(...),
):
    patient_id = user.patient_id
    patient = await session.get(Patient, patient_id)
    repo = DocumentRepository(session, user.tenant_id)

    mime = (file.content_type or "").lower()
    data = await file.read()
    try:
        validate_upload(data, mime)
    except UploadRejected as exc:
        docs = await repo.list_for_patient(patient_id)
        return _render(request, user, "portal/documents.html",
                       patient=patient, documents=docs, error=str(exc))

    store = get_document_store()
    file_key, file_hash = await store.put(tenant_id=user.tenant_id, data=data)

    existing = await repo.get_by_hash(patient_id, file_hash)
    if not existing:
        doc = Document(
            tenant_id=user.tenant_id,
            patient_id=patient_id,
            source_type="patient_upload",
            file_key=file_key,
            file_hash=file_hash,
            original_filename=file.filename,
            mime_type=mime,
            ocr_status="pending",
        )
        await repo.add(doc)
        await session.commit()
        await get_queue().enqueue("ocr_process", document_id=doc.id, tenant_id=user.tenant_id)

    return RedirectResponse("/portal/documents", status_code=status.HTTP_303_SEE_OTHER)


# ──────────────────────────────────────────────
# Appointments
# ──────────────────────────────────────────────

@router.get("/appointments")
async def portal_appointments(request: Request, session: SessionDep, user: PatientUser):
    """List all appointments for the patient, with doctor names resolved for display."""
    patient_id = user.patient_id
    patient = await session.get(Patient, patient_id)

    appts = (
        await session.execute(
            select(Appointment)
            .where(Appointment.patient_id == patient_id)
            .order_by(Appointment.scheduled_at.desc())
        )
    ).scalars().all()

    # Load doctor names for display
    doctor_names: dict[uuid.UUID, str] = {}
    for appt in appts:
        if appt.doctor_id and appt.doctor_id not in doctor_names:
            doc_user = await session.get(User, appt.doctor_id)
            doctor_names[appt.doctor_id] = doc_user.full_name or doc_user.email if doc_user else "Unknown"

    return _render(
        request, user, "portal/appointments.html",
        patient=patient,
        appointments=appts,
        doctor_names=doctor_names,
        error=None,
    )


@router.post("/appointments")
async def portal_book_appointment(  # noqa: D401
    request: Request,
    session: SessionDep,
    user: PatientUser,
    scheduled_date: str = Form(...),
    scheduled_time: str = Form(...),
    reason: str = Form(""),
):
    patient_id = user.patient_id

    try:
        scheduled_at = datetime.fromisoformat(f"{scheduled_date}T{scheduled_time}:00")
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    except ValueError:
        patient = await session.get(Patient, patient_id)
        appts = (
            await session.execute(
                select(Appointment).where(Appointment.patient_id == patient_id)
                .order_by(Appointment.scheduled_at.desc())
            )
        ).scalars().all()
        return _render(request, user, "portal/appointments.html",
                       patient=patient, appointments=appts, doctor_names={},
                       error="Invalid date or time format.")

    appt = Appointment(
        tenant_id=user.tenant_id,
        patient_id=patient_id,
        scheduled_at=scheduled_at,
        reason=reason.strip() or None,
        status="pending",
    )
    session.add(appt)
    await session.commit()
    return RedirectResponse("/portal/appointments", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/appointments/{appt_id}/cancel")
async def portal_cancel_appointment(  # noqa: D401
    request: Request,
    session: SessionDep,
    user: PatientUser,
    appt_id: uuid.UUID,
):
    appt = await session.get(Appointment, appt_id)
    if appt and appt.patient_id == user.patient_id and appt.status in ("pending", "confirmed"):
        appt.status = "cancelled"
        await session.commit()
    return RedirectResponse("/portal/appointments", status_code=status.HTTP_303_SEE_OTHER)


# ──────────────────────────────────────────────
# Messages
# ──────────────────────────────────────────────

@router.get("/messages")
async def portal_messages(request: Request, session: SessionDep, user: PatientUser):
    """Show the patient ↔ doctor message thread and mark all incoming messages as read."""
    patient_id = user.patient_id
    patient = await session.get(Patient, patient_id)

    msgs = (
        await session.execute(
            select(Message)
            .where(Message.patient_id == patient_id)
            .order_by(Message.created_at)
        )
    ).scalars().all()

    # Mark doctor→patient messages as read
    for m in msgs:
        if m.direction == "doctor_to_patient" and m.read_at is None:
            m.read_at = datetime.now(timezone.utc)
    await session.commit()

    return _render(request, user, "portal/messages.html", patient=patient, messages=msgs)


@router.post("/messages")
async def portal_send_message(  # noqa: D401
    request: Request,
    session: SessionDep,
    user: PatientUser,
    body: str = Form(...),
):
    body = body.strip()
    if body:
        msg = Message(
            tenant_id=user.tenant_id,
            patient_id=user.patient_id,
            sender_id=user.id,
            direction="patient_to_doctor",
            body=body,
        )
        session.add(msg)
        await session.commit()
    return RedirectResponse("/portal/messages", status_code=status.HTTP_303_SEE_OTHER)


# ──────────────────────────────────────────────
# Doctor-side: reply to patient message
# ──────────────────────────────────────────────

@router.post("/doctor/messages/{patient_id}/reply")
async def doctor_reply_message(
    request: Request,
    session: SessionDep,
    patient_id: uuid.UUID,
    body: str = Form(...),
):
    """Called from the patient detail page by a doctor/admin."""
    from app.deps import get_optional_user
    user = await get_optional_user(request, session)
    if not user or user.role not in ("admin", "doctor"):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    body = body.strip()
    if body:
        msg = Message(
            tenant_id=user.tenant_id,
            patient_id=patient_id,
            sender_id=user.id,
            direction="doctor_to_patient",
            body=body,
        )
        session.add(msg)
        await session.commit()
    return RedirectResponse(
        f"/patients/ui/{patient_id}#messages", status_code=status.HTTP_303_SEE_OTHER
    )


# ──────────────────────────────────────────────
# Doctor-side: manage appointments
# ──────────────────────────────────────────────

@router.post("/doctor/appointments/{appt_id}/confirm")
async def doctor_confirm_appointment(  # noqa: D401
    request: Request,
    session: SessionDep,
    appt_id: uuid.UUID,
):
    from app.deps import get_optional_user
    user = await get_optional_user(request, session)
    if not user or user.role not in ("admin", "doctor"):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    appt = await session.get(Appointment, appt_id)
    if appt and appt.tenant_id == user.tenant_id:
        appt.status = "confirmed"
        appt.doctor_id = user.id
        await session.commit()
    return RedirectResponse(
        f"/patients/ui/{appt.patient_id}#appointments", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/doctor/appointments/{appt_id}/cancel")
async def doctor_cancel_appointment(  # noqa: D401
    request: Request,
    session: SessionDep,
    appt_id: uuid.UUID,
):
    from app.deps import get_optional_user
    user = await get_optional_user(request, session)
    if not user or user.role not in ("admin", "doctor"):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    appt = await session.get(Appointment, appt_id)
    if appt and appt.tenant_id == user.tenant_id:
        appt.status = "cancelled"
        await session.commit()
    return RedirectResponse(
        f"/patients/ui/{appt.patient_id}#appointments", status_code=status.HTTP_303_SEE_OTHER
    )


# ──────────────────────────────────────────────
# Patient AI chat (patient-scoped context)
# ──────────────────────────────────────────────

class _ChatRequest(BaseModel):
    question: str


class _ChatResponse(BaseModel):
    answer: str


@router.post("/chat", response_model=_ChatResponse)
async def portal_chat(body: _ChatRequest, session: SessionDep, user: PatientUser) -> _ChatResponse:
    """Answer the patient's health question using only their own clinical records as context.

    Context is scoped strictly to the authenticated patient — no cross-patient data is ever
    passed to the LLM. Gracefully degrades if the AI provider is rate-limited.
    """
    from app.ai.agents.chat import chat_answer
    from app.ai.errors import RateLimitExhausted
    from app.db.models import Allergy

    patient_id = user.patient_id
    patient = await session.get(Patient, patient_id)

    problems = (
        await session.execute(select(Problem).where(Problem.patient_id == patient_id))
    ).scalars().all()
    meds = (
        await session.execute(select(Medication).where(Medication.patient_id == patient_id))
    ).scalars().all()
    obs = (
        await session.execute(
            select(Observation).where(Observation.patient_id == patient_id).limit(50)
        )
    ).scalars().all()
    allergies = (
        await session.execute(select(Allergy).where(Allergy.patient_id == patient_id))
    ).scalars().all()
    appts = (
        await session.execute(
            select(Appointment)
            .where(Appointment.patient_id == patient_id, Appointment.scheduled_at >= datetime.now(timezone.utc))
            .order_by(Appointment.scheduled_at)
            .limit(5)
        )
    ).scalars().all()

    context = {
        "patient_name": f"{patient.given_name} {patient.family_name}" if patient else "you",
        "ai_summary": patient.ai_summary if patient else None,
        "problems": [{"label": p.label, "status": p.status} for p in problems],
        "medications": [{"name": m.name, "dose": m.dose, "frequency": m.frequency, "status": m.status} for m in meds],
        "observations": [{"label": o.label, "value": str(o.value_numeric or o.value_text), "unit": o.unit} for o in obs],
        "allergies": [{"substance": a.substance, "reaction": a.reaction, "severity": a.severity} for a in allergies],
        "upcoming_appointments": [{"date": a.scheduled_at.isoformat(), "reason": a.reason, "status": a.status} for a in appts],
    }

    try:
        answer = await chat_answer(body.question, context)
    except RateLimitExhausted:
        answer = "The AI provider is rate-limited right now. Please try again in a moment."
    except Exception:
        answer = "An error occurred. Please try again."
    return _ChatResponse(answer=answer)


# ──────────────────────────────────────────────
# /patient/* URL aliases (canonical patient login/register)
# ──────────────────────────────────────────────

@patient_router.get("/login")
async def patient_login_get(request: Request, session: SessionDep):
    """Canonical patient login page at /patient/login."""
    user = await get_optional_user(request, session)
    if user and user.role == "patient":
        return RedirectResponse("/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "portal/login.html", {"current_user": None, "error": None})


@patient_router.post("/login")
async def patient_login_post(
    request: Request,
    session: SessionDep,
    email: str = Form(...),
    password: str = Form(...),
):
    from app.security import verify_password as _vp
    email = email.strip().lower()
    user = (
        await session.execute(
            select(User).where(User.email == email, User.role == "patient", User.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if not user or not _vp(password, user.password_hash):
        return templates.TemplateResponse(
            request, "portal/login.html",
            {"current_user": None, "error": "Invalid email or password."}
        )
    from app.security import create_access_token as _cat
    token = _cat(user_id=user.id, tenant_id=user.tenant_id)
    resp = RedirectResponse("/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    _set_session(resp, token)
    return resp


@patient_router.get("/register")
async def patient_register_get(request: Request, session: SessionDep):
    """Canonical registration page at /patient/register."""
    user = await get_optional_user(request, session)
    if user and user.role == "patient":
        return RedirectResponse("/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "portal/register.html", {"current_user": None, "error": None})


@patient_router.post("/register")
async def patient_register_post(  # noqa: D401
    request: Request,
    session: SessionDep,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
):
    # Delegate to the /portal/register handler logic by forwarding
    # Build a fake Request-like form and reuse the existing function
    from app.security import hash_password as _hp
    email = email.strip().lower()
    existing_user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing_user:
        return templates.TemplateResponse(
            request, "portal/register.html",
            {"current_user": None, "error": "An account with this email already exists."}
        )
    patient = (await session.execute(select(Patient).where(Patient.email == email))).scalar_one_or_none()
    if patient:
        tenant_id = patient.tenant_id
    else:
        from app.db.models import Tenant
        import random, string
        tenant = Tenant(name=f"patient-{email}")
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id
        name_parts = full_name.strip().split(" ", 1)
        given = name_parts[0] if name_parts else email.split("@")[0]
        family = name_parts[1] if len(name_parts) > 1 else ""
        mrn = "P" + "".join(random.choices(string.digits, k=8))
        patient = Patient(tenant_id=tenant_id, mrn=mrn, given_name=given, family_name=family, email=email)
        session.add(patient)
        await session.flush()
    new_user = User(
        tenant_id=tenant_id, email=email,
        full_name=full_name.strip() or None,
        password_hash=_hp(password), role="patient", patient_id=patient.id,
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    from app.security import create_access_token as _cat
    token = _cat(user_id=new_user.id, tenant_id=new_user.tenant_id)
    resp = RedirectResponse("/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    _set_session(resp, token)
    return resp
