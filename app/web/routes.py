"""Web UI routes — HTML responses rendered via Jinja2 templates.

This module owns every browser-facing page for doctors and admins:
  - /           → redirect to dashboard or login
  - /doctor/login, /admin/login, /register, /logout
  - /dashboard  — clinic overview stats
  - /admin      — super-admin tenant management
  - /admin/reprocess-all — re-queue all OCR-complete documents
  - /patients/ui/* — patient CRUD, document upload, flag resolution
  - /documents/ui/* — document viewer, reprocess trigger, SSE stream
  - /admin/usage — LLM token usage log

Auth model: JWT stored in an httponly session cookie. OptionalUser resolves the
cookie and returns None when absent. Routes that require auth redirect to the
appropriate login page rather than returning 401/403.
"""
import uuid
from datetime import date

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.models import Document, Patient, User
from app.db.repositories.audit import AuditRepository
from app.db.repositories.dashboard import DashboardRepository
from app.db.repositories.document import DocumentRepository
from app.db.repositories.extraction import ExtractionRepository
from app.db.repositories.medication import MedicationRepository
from app.db.repositories.observation import ObservationRepository
from app.db.repositories.patient import PatientRepository
from app.db.repositories.problem import ProblemRepository
from app.db.repositories.reconcile import ReconcileFlagRepository
from app.db.repositories.tenant import TenantRepository
from app.db.repositories.user import UserRepository
from app.deps import SESSION_COOKIE, AdminUser, OptionalUser, SessionDep, get_optional_user
from app.ingestion.store import get_document_store
from app.queue import get_queue
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.patient import PatientCreate
from app.events import get_event_bus
from app.logging import get_logger

log = get_logger(__name__)
from app.security import create_access_token, hash_password, verify_password
from app.validation import UploadRejected, validate_upload
from app.web.templates import templates

router = APIRouter(tags=["web"])


def _set_session(response: RedirectResponse, token: str) -> None:
    """Write the JWT to the httponly session cookie on a redirect response."""
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


def _render(request: Request, user: User | None, template: str, **ctx):
    """Render a Jinja2 template, injecting `current_user` into every context."""
    return templates.TemplateResponse(
        request,
        template,
        {"current_user": user, **ctx},
    )


@router.get("/")
async def root(user: OptionalUser) -> RedirectResponse:
    target = "/dashboard" if user else "/login"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def _fmt_bytes(n: int) -> str:
    """Format a byte count as a human-readable string (e.g. "3.2 MB")."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


@router.get("/dashboard")
async def dashboard(request: Request, session: SessionDep, user: OptionalUser):
    """Clinic overview: patient count, document status, storage stats, open flags."""
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    repo = DashboardRepository(session, user.tenant_id)
    settings = get_settings()
    patient_count = await repo.patient_count()
    status_counts = await repo.document_counts_by_status()
    recent = await repo.recent_uploads(limit=10)
    needs_attention = await repo.docs_needing_attention(limit=10)
    storage_bytes, file_count = repo.storage_stats(settings.local_store_path)
    open_flags = await repo.open_flag_count()
    critical_flags = await repo.critical_flag_count()
    return _render(
        request,
        user,
        "dashboard.html",
        patient_count=patient_count,
        status_counts=status_counts,
        needs_attention_count=(
            status_counts.get("failed", 0)
            + status_counts.get("no_text", 0)
            + status_counts.get("unsupported", 0)
        ),
        recent=recent,
        needs_attention=needs_attention,
        storage_bytes=storage_bytes,
        storage_pretty=_fmt_bytes(storage_bytes),
        file_count=file_count,
        open_flags=open_flags,
        critical_flags=critical_flags,
    )


@router.get("/login")
async def login_redirect(user: OptionalUser):
    """Redirect legacy /login to the role-appropriate destination."""
    if user:
        if user.role == "patient":
            return RedirectResponse("/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        if user.role == "admin":
            return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse("/doctor/login", status_code=status.HTTP_303_SEE_OTHER)


# ── Doctor login ──────────────────────────────────────────────────────────────

@router.get("/doctor/login")
async def doctor_login_get(request: Request, user: OptionalUser):
    """Render the doctor login page; redirect to /dashboard if already authenticated."""
    if user and user.role == "doctor":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, None, "login.html", role="doctor")


@router.post("/doctor/login")
async def doctor_login_post(  # noqa: D401 — imperative mood fine for handlers
    request: Request,
    session: SessionDep,
    tenant_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    try:
        body = LoginRequest(tenant_name=tenant_name, email=email, password=password)
    except ValidationError:
        return _render(request, None, "login.html", role="doctor", error="Check your inputs and try again.")

    tenant = await TenantRepository(session).get_by_name(body.tenant_name)
    if not tenant:
        return _render(request, None, "login.html", role="doctor", error="Invalid credentials.")
    user_repo = UserRepository(session, tenant.id)
    user = await user_repo.get_by_email(body.email)
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        return _render(request, None, "login.html", role="doctor", error="Invalid credentials.")
    if user.role != "doctor":
        return _render(request, None, "login.html", role="doctor", error="This account is not a doctor account.")

    await AuditRepository(session, tenant.id).record(
        user_id=user.id, action="login", resource_type="session",
        method="POST", path="/doctor/login", status_code=200,
    )
    await session.commit()

    token = create_access_token(user_id=user.id, tenant_id=tenant.id)
    response = RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    _set_session(response, token)
    return response


# ── Admin login ───────────────────────────────────────────────────────────────

@router.get("/admin/login")
async def admin_login_get(request: Request, user: OptionalUser):
    if user and user.role == "admin":
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, None, "login.html", role="admin")


@router.post("/admin/login")
async def admin_login_post(
    request: Request,
    session: SessionDep,
    tenant_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    try:
        body = LoginRequest(tenant_name=tenant_name, email=email, password=password)
    except ValidationError:
        return _render(request, None, "login.html", role="admin", error="Check your inputs and try again.")

    tenant = await TenantRepository(session).get_by_name(body.tenant_name)
    if not tenant:
        return _render(request, None, "login.html", role="admin", error="Invalid credentials.")
    user_repo = UserRepository(session, tenant.id)
    user = await user_repo.get_by_email(body.email)
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        return _render(request, None, "login.html", role="admin", error="Invalid credentials.")
    if user.role != "admin":
        return _render(request, None, "login.html", role="admin", error="This account is not an admin account.")

    await AuditRepository(session, tenant.id).record(
        user_id=user.id, action="login", resource_type="session",
        method="POST", path="/admin/login", status_code=200,
    )
    await session.commit()

    token = create_access_token(user_id=user.id, tenant_id=tenant.id)
    response = RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    _set_session(response, token)
    return response


@router.get("/register")
async def register_get(request: Request, user: OptionalUser):
    """Render the new-tenant registration page."""
    if user:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, None, "register.html")


@router.post("/register")
async def register_post(  # noqa: D401
    request: Request,
    session: SessionDep,
    tenant_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
):
    try:
        body = RegisterRequest(
            tenant_name=tenant_name,
            email=email,
            password=password,
            full_name=full_name or None,
        )
    except ValidationError as exc:
        msg = exc.errors()[0]["msg"] if exc.errors() else "Invalid input"
        return _render(request, None, "register.html", error=msg)

    tenant_repo = TenantRepository(session)
    if await tenant_repo.get_by_name(body.tenant_name):
        return _render(
            request, None, "register.html", error="A tenant with that name already exists."
        )

    tenant = await tenant_repo.create(body.tenant_name)
    user = User(
        tenant_id=tenant.id,
        email=body.email.lower(),
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role="doctor",
    )
    session.add(user)
    await session.flush()

    await AuditRepository(session, tenant.id).record(
        user_id=user.id,
        action="register",
        resource_type="tenant",
        resource_id=str(tenant.id),
        method="POST",
        path="/register",
        status_code=201,
    )
    await session.commit()

    token = create_access_token(user_id=user.id, tenant_id=tenant.id)
    response = RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    _set_session(response, token)
    return response


@router.post("/logout")
async def logout() -> RedirectResponse:
    """Clear the session cookie and redirect to the doctor login page."""
    response = RedirectResponse("/doctor/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


# ---------------------------------------------------------------------------
# Admin auth
# ---------------------------------------------------------------------------

@router.get("/admin/login")
async def admin_login_get(request: Request, user: OptionalUser):
    if user and user.role == "admin":
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, None, "admin_login.html")


@router.post("/admin/login")
async def admin_login_post(
    request: Request,
    session: SessionDep,
    email: str = Form(...),
    password: str = Form(...),
):
    from sqlalchemy import select as _select

    # Search for admin user by email across all tenants
    stmt = _select(User).where(
        User.email == email.lower().strip(),
        User.role == "admin",
        User.is_active.is_(True),
    )
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return _render(request, None, "admin_login.html", error="Invalid admin credentials.")

    await AuditRepository(session, user.tenant_id).record(
        user_id=user.id,
        action="admin_login",
        resource_type="session",
        method="POST",
        path="/admin/login",
        status_code=200,
    )
    await session.commit()

    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id)
    response = RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    _set_session(response, token)
    return response


@router.get("/admin")
async def admin_home(request: Request, session: SessionDep, user: AdminUser):
    """Super-admin dashboard: tenant list, user list, total LLM token usage."""
    from sqlalchemy import func, select as _select

    from app.db.models import LLMCallLog, Tenant

    tenants = (await session.execute(_select(Tenant).order_by(Tenant.name))).scalars().all()
    from app.db.models import Patient as _Patient

    patient_counts: dict[uuid.UUID, int] = {}
    for t in tenants:
        cnt = (
            await session.execute(
                _select(func.count()).select_from(_Patient).where(_Patient.tenant_id == t.id)
            )
        ).scalar_one()
        patient_counts[t.id] = cnt

    total_tokens = (
        await session.execute(
            _select(func.sum(LLMCallLog.total_tokens))
        )
    ).scalar_one() or 0

    users = (await session.execute(_select(User).order_by(User.created_at.desc()))).scalars().all()

    return _render(
        request, user, "admin_home.html",
        tenants=tenants,
        patient_counts=patient_counts,
        users=users,
        total_tokens=total_tokens,
    )


@router.post("/admin/logout")
async def admin_logout() -> RedirectResponse:
    response = RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/patients/ui")
async def patients_list(request: Request, session: SessionDep, user: OptionalUser):
    """List all patients in the current tenant."""
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    repo = PatientRepository(session, user.tenant_id)
    patients = await repo.list(limit=200, offset=0)
    return _render(request, user, "patients_list.html", patients=patients)


@router.get("/patients/ui/new")
async def patient_new_get(request: Request, session: SessionDep, user: OptionalUser):
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, user, "patient_new.html")


_PATIENT_FORM_FIELDS = [
    "mrn", "given_name", "family_name", "sex", "date_of_birth",
    "phone", "email", "address_line1", "address_line2", "city", "state",
    "zip_code", "country", "blood_type", "chief_complaint", "allergies_summary",
    "primary_physician", "emergency_contact_name", "emergency_contact_phone",
    "emergency_contact_relation", "insurance_provider", "insurance_id",
]


async def _patient_from_form(request: Request) -> dict:
    """Parse patient form fields from a multipart/form-data request."""
    form = await request.form()
    data: dict = {}
    for f in _PATIENT_FORM_FIELDS:
        v = form.get(f, "")
        data[f] = v or None
    if data.get("date_of_birth"):
        try:
            data["date_of_birth"] = date.fromisoformat(str(data["date_of_birth"]))
        except ValueError:
            data["date_of_birth"] = None
    return data


@router.post("/patients/ui")
async def patient_new_post(request: Request, session: SessionDep):
    user = await get_optional_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    data = await _patient_from_form(request)
    try:
        body = PatientCreate(**data)
    except ValidationError as exc:
        msg = exc.errors()[0]["msg"] if exc.errors() else "Invalid input"
        return _render(request, user, "patient_new.html", error=msg)

    patient = Patient(tenant_id=user.tenant_id, **{
        f: getattr(body, f) for f in _PATIENT_FORM_FIELDS if f != "mrn"
    }, mrn=body.mrn, demographics={})

    repo = PatientRepository(session, user.tenant_id)
    try:
        await repo.add(patient)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        await session.refresh(user)
        return _render(request, user, "patient_new.html", error="A patient with that MRN already exists.")

    return RedirectResponse(f"/patients/ui/{patient.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/patients/ui/{patient_id}")
async def patient_detail(  # noqa: D401
    request: Request,
    session: SessionDep,
    user: OptionalUser,
    patient_id: uuid.UUID,
    portal_created: str = "",
):
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        return RedirectResponse(
            "/patients/ui?missing=1", status_code=status.HTTP_303_SEE_OTHER
        )
    documents = await DocumentRepository(session, user.tenant_id).list_for_patient(patient_id)
    observations = await ObservationRepository(session, user.tenant_id).list_for_patient(patient_id)
    medications = await MedicationRepository(session, user.tenant_id).list_for_patient(patient_id)
    problems = await ProblemRepository(session, user.tenant_id).list_for_patient(patient_id)
    from app.db.repositories.allergy import AllergyRepository
    allergies = await AllergyRepository(session, user.tenant_id).list_for_patient(patient_id)
    flags = await ReconcileFlagRepository(session, user.tenant_id).list_for_patient(patient_id, resolved=False)
    docs_by_id = {str(d.id): d for d in documents}

    # Portal: messages + appointments + linked portal account
    from sqlalchemy import select as _select
    from app.db.models import Appointment, Message
    messages = (
        await session.execute(
            _select(Message)
            .where(Message.patient_id == patient_id)
            .order_by(Message.created_at)
        )
    ).scalars().all()
    appointments = (
        await session.execute(
            _select(Appointment)
            .where(Appointment.patient_id == patient_id)
            .order_by(Appointment.scheduled_at.desc())
        )
    ).scalars().all()
    unread_msg_count = sum(
        1 for m in messages
        if m.direction == "patient_to_doctor" and m.read_at is None
    )
    portal_user = (
        await session.execute(
            _select(User).where(User.patient_id == patient_id, User.role == "patient")
        )
    ).scalar_one_or_none()

    return _render(
        request,
        user,
        "patient_detail.html",
        patient=patient,
        documents=documents,
        docs_by_id=docs_by_id,
        has_pending=any(d.ocr_status == "pending" for d in documents),
        observations=observations,
        medications=medications,
        problems=problems,
        allergies=allergies,
        reconcile_flags=flags,
        messages=messages,
        appointments=appointments,
        unread_msg_count=unread_msg_count,
        portal_user=portal_user,
        portal_register_error=None,
        flash="Portal account created. Patient can now log in at /patient/login." if portal_created else None,
    )


@router.post("/patients/ui/{patient_id}/create-portal-account")
async def create_patient_portal_account(
    request: Request,
    session: SessionDep,
    patient_id: uuid.UUID,
    email: str = Form(...),
    password: str = Form(...),
):
    """Doctor creates a portal login for an existing patient."""
    from sqlalchemy import select as _select
    from app.db.models import Appointment, Message
    from app.db.repositories.allergy import AllergyRepository
    from app.security import hash_password as _hash

    user = await get_optional_user(request, session)
    if not user or user.role not in ("admin", "doctor"):
        return RedirectResponse("/doctor/login", status_code=status.HTTP_303_SEE_OTHER)

    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        return RedirectResponse("/patients/ui", status_code=status.HTTP_303_SEE_OTHER)

    email = email.strip().lower()

    # Check email not already taken
    existing = (
        await session.execute(_select(User).where(User.email == email))
    ).scalar_one_or_none()

    async def _reload_detail(error: str):
        documents = await DocumentRepository(session, user.tenant_id).list_for_patient(patient_id)
        observations = await ObservationRepository(session, user.tenant_id).list_for_patient(patient_id)
        medications = await MedicationRepository(session, user.tenant_id).list_for_patient(patient_id)
        problems = await ProblemRepository(session, user.tenant_id).list_for_patient(patient_id)
        allergies = await AllergyRepository(session, user.tenant_id).list_for_patient(patient_id)
        flags = await ReconcileFlagRepository(session, user.tenant_id).list_for_patient(patient_id, resolved=False)
        docs_by_id = {str(d.id): d for d in documents}
        messages = (await session.execute(_select(Message).where(Message.patient_id == patient_id).order_by(Message.created_at))).scalars().all()
        appointments = (await session.execute(_select(Appointment).where(Appointment.patient_id == patient_id).order_by(Appointment.scheduled_at.desc()))).scalars().all()
        unread_msg_count = sum(1 for m in messages if m.direction == "patient_to_doctor" and m.read_at is None)
        return _render(
            request, user, "patient_detail.html",
            patient=patient, documents=documents, docs_by_id=docs_by_id,
            has_pending=any(d.ocr_status == "pending" for d in documents),
            observations=observations, medications=medications, problems=problems,
            allergies=allergies, reconcile_flags=flags,
            messages=messages, appointments=appointments, unread_msg_count=unread_msg_count,
            portal_user=None, portal_register_error=error,
        )

    if existing:
        return await _reload_detail("That email is already registered to another account.")

    new_user = User(
        tenant_id=user.tenant_id,
        email=email,
        full_name=f"{patient.given_name} {patient.family_name}",
        password_hash=_hash(password),
        role="patient",
        patient_id=patient_id,
    )
    # Also save email onto the patient record if not set
    if not patient.email:
        patient.email = email
    session.add(new_user)
    await session.commit()

    return RedirectResponse(
        f"/patients/ui/{patient_id}?portal_created=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/patients/ui/{patient_id}/edit")
async def patient_edit_get(request: Request, session: SessionDep, patient_id: uuid.UUID):
    user = await get_optional_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        return RedirectResponse("/patients/ui", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, user, "patient_edit.html", patient=patient)


@router.post("/patients/ui/{patient_id}/edit")
async def patient_edit_post(request: Request, session: SessionDep, patient_id: uuid.UUID):
    user = await get_optional_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        return RedirectResponse("/patients/ui", status_code=status.HTTP_303_SEE_OTHER)
    data = await _patient_from_form(request)
    for field, value in data.items():
        if field != "mrn" and hasattr(patient, field):
            setattr(patient, field, value)
    await session.commit()
    return RedirectResponse(f"/patients/ui/{patient_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/patients/ui/{patient_id}/flags/{flag_id}/resolve")
async def resolve_flag(
    request: Request,
    session: SessionDep,
    patient_id: uuid.UUID,
    flag_id: uuid.UUID,
):
    user = await get_optional_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    action = form.get("action", "keep_existing")

    from app.db.models import ReconcileFlag
    from app.db.models.patient import Patient as PatientModel

    flag = await session.get(ReconcileFlag, flag_id)
    if flag and flag.tenant_id == user.tenant_id and flag.patient_id == patient_id:
        if action in ("apply_document", "edit_apply") and flag.resource_type == "patient_profile":
            field = flag.details.get("field")
            if action == "edit_apply":
                doc_val = str(form.get("corrected_value", "") or "").strip() or flag.details.get("document_value")
            else:
                doc_val = flag.details.get("document_value")
            if field and doc_val:
                patient = await session.get(PatientModel, patient_id)
                if patient:
                    if field == "date_of_birth":
                        from datetime import date as _date
                        try:
                            doc_val = _date.fromisoformat(str(doc_val))
                        except ValueError:
                            pass
                    setattr(patient, field, doc_val)
            flag.resolved_by = "doctor_apply"
        else:
            flag.resolved_by = "doctor_dismiss"
        flag.resolved = True
        await session.commit()

    return RedirectResponse(f"/patients/ui/{patient_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/patients/ui/{patient_id}/delete")
async def patient_delete_post(request: Request, session: SessionDep, patient_id: uuid.UUID):
    user = await get_optional_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if patient:
        await session.delete(patient)
        await session.commit()
    return RedirectResponse("/patients/ui", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/patients/ui/{patient_id}/documents")
async def documents_panel(
    request: Request,
    session: SessionDep,
    user: OptionalUser,
    patient_id: uuid.UUID,
):
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        return RedirectResponse("/patients/ui", status_code=status.HTTP_303_SEE_OTHER)
    documents = await DocumentRepository(session, user.tenant_id).list_for_patient(patient_id)
    return templates.TemplateResponse(
        request,
        "_documents_panel.html",
        {
            "current_user": user,
            "patient": patient,
            "documents": documents,
            "has_pending": any(d.ocr_status == "pending" for d in documents),
        },
    )


@router.get("/documents/ui/{document_id}")
async def document_viewer(  # noqa: D401
    request: Request,
    session: SessionDep,
    user: OptionalUser,
    document_id: uuid.UUID,
):
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    doc = await DocumentRepository(session, user.tenant_id).get(document_id)
    if not doc:
        return RedirectResponse("/patients/ui", status_code=status.HTTP_303_SEE_OTHER)
    extractions = await ExtractionRepository(session, user.tenant_id).list_for_document(document_id)
    ps = doc.pipeline_status or {}
    pipeline_active = (
        doc.ocr_status == "pending"
        or any(s.get("status") == "running" for s in ps.values())
        or (doc.ocr_status == "ok" and ps.get("summarize", {}).get("status") != "ok")
    )
    return _render(
        request, user, "document_viewer.html",
        document=doc,
        extractions=extractions,
        pipeline_active=pipeline_active,
    )


@router.post("/documents/ui/{document_id}/reprocess")
async def reprocess_document_web(  # noqa: D401
    request: Request,
    session: SessionDep,
    document_id: uuid.UUID,
):
    user = await get_optional_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    doc = await DocumentRepository(session, user.tenant_id).get(document_id)
    if doc:
        await get_queue().enqueue(
            "extract_document", document_id=doc.id, tenant_id=user.tenant_id
        )
    return RedirectResponse(
        f"/documents/ui/{document_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/documents/ui/{document_id}/text-partial")
async def document_text_partial(  # noqa: D401
    request: Request,
    session: SessionDep,
    user: OptionalUser,
    document_id: uuid.UUID,
):
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    doc = await DocumentRepository(session, user.tenant_id).get(document_id)
    if not doc:
        return RedirectResponse("/patients/ui", status_code=status.HTTP_303_SEE_OTHER)
    from fastapi.responses import HTMLResponse

    if doc.ocr_status == "pending":
        return HTMLResponse(
            '<span class="text-amber-700 text-xs">Extraction in progress…</span>'
        )
    if doc.ocr_text:
        import html

        return HTMLResponse(html.escape(doc.ocr_text))
    label = {
        "no_text": "No text found in this document.",
        "unsupported": "Text extraction not wired for this file type yet.",
        "failed": "Extraction failed.",
    }.get(doc.ocr_status, "No text extracted.")
    return HTMLResponse(f'<span class="text-slate-400 text-xs">{label}</span>')


@router.post("/documents/ui/{document_id}/delete")
async def document_delete(
    request: Request,
    session: SessionDep,
    document_id: uuid.UUID,
):
    user = await get_optional_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    repo = DocumentRepository(session, user.tenant_id)
    doc = await repo.get(document_id)
    if not doc:
        return RedirectResponse("/patients/ui", status_code=status.HTTP_303_SEE_OTHER)

    patient_id = doc.patient_id

    # Remove file from store
    try:
        store = get_document_store()
        store.delete(tenant_id=user.tenant_id, file_key=doc.file_key)
    except Exception:  # noqa: BLE001
        pass  # file may already be gone; proceed with DB delete

    from app.db.repositories.audit import AuditRepository as _AuditRepo
    await _AuditRepo(session, user.tenant_id).record(
        user_id=user.id,
        action="document_deleted",
        resource_type="document",
        resource_id=str(document_id),
        method="POST",
        path=request.url.path,
        status_code=200,
    )

    await session.delete(doc)
    await session.commit()

    return RedirectResponse(
        f"/patients/ui/{patient_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/documents/{document_id}/events")
async def document_pipeline_events(
    request: Request,
    session: SessionDep,
    user: OptionalUser,
    document_id: uuid.UUID,
):
    """SSE stream of pipeline step events for a document.

    Emits JSON-encoded event objects:
      {"type": "step", "step": "classify", "status": "ok", "detail": "..."}
      {"type": "done"} | {"type": "failed"} | {"type": "keepalive"}
    """
    from sse_starlette.sse import EventSourceResponse

    if not user:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    doc = await DocumentRepository(session, user.tenant_id).get(document_id)
    if not doc:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "not found"}, status_code=404)

    import asyncio
    import json as _json

    async def _generator():
        from app.db.session import SessionLocal

        bus = get_event_bus()

        # Register subscriber queue BEFORE reading DB so no events are missed
        # between the snapshot and the live drain.
        live_q: asyncio.Queue = asyncio.Queue(maxsize=128)
        bus._subscribers[document_id].add(live_q)
        try:
            # Replay current state from DB so browser catches up immediately
            async with SessionLocal() as gs:
                current = await gs.get(doc.__class__, document_id)

            already_done = False
            if current:
                ps = current.pipeline_status or {}
                ocr_st = current.ocr_status
                step_order = ["ocr", "classify", "extract", "persist", "profile", "summarize"]
                for key in step_order:
                    if key == "ocr":
                        if ocr_st in ("ok", "failed"):
                            yield {"data": _json.dumps({"type": "step", "step": "ocr", "status": ocr_st, "detail": ocr_st})}
                        elif ocr_st == "pending":
                            yield {"data": _json.dumps({"type": "step", "step": "ocr", "status": "running", "detail": ""})}
                    elif key in ps:
                        s = ps[key]
                        yield {"data": _json.dumps({"type": "step", "step": key, "status": s.get("status", "pending"), "detail": s.get("detail", "")})}

                summarize_ok = ps.get("summarize", {}).get("status") == "ok"
                extract_skipped = ps.get("extract", {}).get("status") == "skipped"
                profile_terminal = ps.get("profile", {}).get("status") in ("ok", "failed", "skipped")
                persist_ok = ps.get("persist", {}).get("status") == "ok"
                any_running = any(s.get("status") == "running" for s in ps.values())
                # Done if summarize finished, or extract was skipped + profile done,
                # or persist finished (old docs without summarize step), or OCR ok but
                # extraction was never triggered (no classify key at all, not running).
                extraction_never_started = (
                    ocr_st == "ok"
                    and "classify" not in ps
                    and not any_running
                )
                already_done = (
                    summarize_ok
                    or (extract_skipped and profile_terminal)
                    or (persist_ok and not any_running)
                )

            if extraction_never_started and not already_done:
                # OCR done but extraction job was never picked up — re-enqueue it now
                try:
                    from app.queue import get_queue
                    await get_queue().enqueue(
                        "extract_document",
                        document_id=document_id,
                        tenant_id=current.tenant_id,
                    )
                    log.info("extraction_reenqueued_from_sse", document_id=str(document_id))
                except Exception:
                    already_done = True  # queue unavailable; fall through to done

            if already_done:
                yield {"data": _json.dumps({"type": "done"})}
                return

            # Drain live events + periodic DB poll every 3 s as a catch-all.
            # The poll re-reads pipeline_status and pushes any state the browser
            # hasn't seen yet, covering every race condition between emit and connect.
            known: dict[str, str] = {}  # step → last status sent to browser
            last_poll = asyncio.get_event_loop().time()
            POLL_INTERVAL = 3.0

            deadline = asyncio.get_event_loop().time() + 180.0
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                # Wait at most until next poll is due
                wait = min(remaining, POLL_INTERVAL - (asyncio.get_event_loop().time() - last_poll))
                wait = max(wait, 0.05)
                try:
                    event = await asyncio.wait_for(live_q.get(), timeout=wait)
                    if event.get("type") == "step":
                        known[event["step"]] = event["status"]
                    yield {"data": _json.dumps(event)}
                    if event.get("type") in ("done", "failed"):
                        return
                except asyncio.TimeoutError:
                    pass  # fall through to poll

                if asyncio.get_event_loop().time() - last_poll >= POLL_INTERVAL:
                    last_poll = asyncio.get_event_loop().time()
                    # Re-read DB; push steps whose status changed since last send
                    async with SessionLocal() as gs:
                        fresh = await gs.get(doc.__class__, document_id)
                    if not fresh:
                        break
                    fps = fresh.pipeline_status or {}
                    focr = fresh.ocr_status
                    # OCR
                    ocr_st = "ok" if focr == "ok" else ("failed" if focr == "failed" else "running")
                    if known.get("ocr") != ocr_st:
                        known["ocr"] = ocr_st
                        yield {"data": _json.dumps({"type": "step", "step": "ocr", "status": ocr_st, "detail": focr})}
                    # Other steps
                    for key in ["classify", "extract", "persist", "profile", "summarize"]:
                        if key in fps:
                            st = fps[key].get("status", "pending")
                            if known.get(key) != st:
                                known[key] = st
                                yield {"data": _json.dumps({"type": "step", "step": key, "status": st, "detail": fps[key].get("detail", "")})}
                    # Check done
                    sum_ok = fps.get("summarize", {}).get("status") == "ok"
                    ext_skip = fps.get("extract", {}).get("status") == "skipped"
                    prof_done = fps.get("profile", {}).get("status") in ("ok", "failed", "skipped")
                    if sum_ok or (ext_skip and prof_done):
                        yield {"data": _json.dumps({"type": "done"})}
                        return
                    # keepalive
                    yield {"data": _json.dumps({"type": "keepalive"})}

                if await request.is_disconnected():
                    break
        finally:
            bus._subscribers[document_id].discard(live_q)
            if not bus._subscribers[document_id]:
                bus._subscribers.pop(document_id, None)

    return EventSourceResponse(_generator())


@router.post("/patients/ui/{patient_id}/documents")
async def upload_document_web(  # noqa: D401
    request: Request,
    session: SessionDep,
    patient_id: uuid.UUID,
    file: UploadFile = File(...),
):
    user = await get_optional_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        return RedirectResponse("/patients/ui", status_code=status.HTTP_303_SEE_OTHER)

    repo = DocumentRepository(session, user.tenant_id)

    async def _render_panel(error: str | None = None):
        documents = await repo.list_for_patient(patient_id)
        return templates.TemplateResponse(
            request,
            "_documents_panel.html",
            {
                "current_user": user,
                "patient": patient,
                "documents": documents,
                "has_pending": any(d.ocr_status == "pending" for d in documents),
                "upload_error": error,
            },
        )

    mime = (file.content_type or "").lower()
    data = await file.read()
    try:
        validate_upload(data, mime)
    except UploadRejected as exc:
        return await _render_panel(str(exc))

    store = get_document_store()
    file_key, file_hash = await store.put(tenant_id=user.tenant_id, data=data)

    existing = await repo.get_by_hash(patient_id, file_hash)
    if existing is not None:
        doc = existing
    else:
        doc = Document(
            tenant_id=user.tenant_id,
            patient_id=patient_id,
            source_type="upload",
            file_key=file_key,
            file_hash=file_hash,
            original_filename=file.filename,
            mime_type=mime,
            ocr_status="pending",
        )
        await repo.add(doc)
        await session.commit()
        await get_queue().enqueue(
            "ocr_process", document_id=doc.id, tenant_id=user.tenant_id
        )

    from fastapi.responses import HTMLResponse
    redirect_url = f"/documents/ui/{doc.id}"
    # HTMX upload triggers a boosted form; use HX-Redirect so the browser navigates
    response = HTMLResponse(content="", status_code=200)
    response.headers["HX-Redirect"] = redirect_url
    return response


@router.get("/activity")
async def activity_log(  # noqa: D401
    request: Request,
    session: SessionDep,
    user: OptionalUser,
    page: int = 1,
    action_filter: str = "",
):
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    from sqlalchemy import select as _select

    from app.db.models import AuditLog

    PAGE_SIZE = 50
    offset = (page - 1) * PAGE_SIZE
    stmt = (
        _select(AuditLog)
        .where(AuditLog.tenant_id == user.tenant_id)
    )
    if action_filter:
        stmt = stmt.where(AuditLog.action == action_filter)
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(PAGE_SIZE + 1)
    rows = (await session.execute(stmt)).scalars().all()
    has_next = len(rows) > PAGE_SIZE
    entries = rows[:PAGE_SIZE]

    # Distinct action types for the filter dropdown
    action_types_stmt = (
        _select(AuditLog.action)
        .where(AuditLog.tenant_id == user.tenant_id)
        .distinct()
        .order_by(AuditLog.action)
    )
    action_types = (await session.execute(action_types_stmt)).scalars().all()

    return _render(
        request,
        user,
        "activity.html",
        entries=entries,
        page=page,
        has_next=has_next,
        action_filter=action_filter,
        action_types=action_types,
    )


@router.get("/admin/usage")
async def admin_usage(  # noqa: D401
    request: Request,
    session: SessionDep,
    user: AdminUser,
):

    from sqlalchemy import func, select as _select

    from app.db.models import LLMCallLog

    rows = (
        await session.execute(
            _select(
                LLMCallLog.role,
                LLMCallLog.model,
                func.sum(LLMCallLog.prompt_tokens).label("prompt_tokens"),
                func.sum(LLMCallLog.completion_tokens).label("completion_tokens"),
                func.sum(LLMCallLog.total_tokens).label("total_tokens"),
                func.count(LLMCallLog.id).label("calls"),
            )
            .where(LLMCallLog.tenant_id == user.tenant_id)
            .group_by(LLMCallLog.role, LLMCallLog.model)
            .order_by(func.sum(LLMCallLog.total_tokens).desc())
        )
    ).all()

    totals_row = (
        await session.execute(
            _select(
                func.sum(LLMCallLog.prompt_tokens),
                func.sum(LLMCallLog.completion_tokens),
                func.sum(LLMCallLog.total_tokens),
                func.count(LLMCallLog.id),
            ).where(LLMCallLog.tenant_id == user.tenant_id)
        )
    ).one()

    totals = {
        "prompt_tokens": totals_row[0] or 0,
        "completion_tokens": totals_row[1] or 0,
        "total_tokens": totals_row[2] or 0,
        "calls": totals_row[3] or 0,
    }

    return _render(request, user, "admin_usage.html", rows=rows, totals=totals)


@router.post("/admin/reprocess-all")
async def reprocess_all_documents(
    request: Request,
    session: SessionDep,
    user: AdminUser,
):
    """Re-queue extraction for every document that has completed OCR."""
    from sqlalchemy import select as _select

    stmt = (
        _select(Document)
        .where(Document.tenant_id == user.tenant_id)
        .where(Document.ocr_status == "ok")
    )
    docs = (await session.execute(stmt)).scalars().all()
    q = get_queue()
    count = 0
    for doc in docs:
        await q.enqueue("extract_document", document_id=doc.id, tenant_id=user.tenant_id)
        count += 1
    log.info("reprocess_all_enqueued", count=count, tenant_id=str(user.tenant_id))
    return RedirectResponse(
        f"/admin/usage?reprocessed={count}", status_code=status.HTTP_303_SEE_OTHER
    )
