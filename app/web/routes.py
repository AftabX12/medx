import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.models import Document, Patient, User
from app.db.repositories.audit import AuditRepository
from app.db.repositories.dashboard import DashboardRepository
from app.db.repositories.document import DocumentRepository
from app.db.repositories.patient import PatientRepository
from app.db.repositories.tenant import TenantRepository
from app.db.repositories.user import UserRepository
from app.deps import SESSION_COOKIE, OptionalUser, SessionDep, get_optional_user
from app.ingestion.ocr import process_document
from app.ingestion.store import get_document_store
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.patient import PatientCreate
from app.security import create_access_token, hash_password, verify_password
from app.web.templates import templates

_ALLOWED_MIME = {"application/pdf", "image/png", "image/jpeg", "image/jpg"}
_MAX_BYTES = 25 * 1024 * 1024

router = APIRouter(tags=["web"])


def _set_session(response: RedirectResponse, token: str) -> None:
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
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


@router.get("/dashboard")
async def dashboard(request: Request, session: SessionDep, user: OptionalUser):
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    repo = DashboardRepository(session, user.tenant_id)
    settings = get_settings()
    patient_count = await repo.patient_count()
    status_counts = await repo.document_counts_by_status()
    recent = await repo.recent_uploads(limit=10)
    needs_attention = await repo.docs_needing_attention(limit=10)
    storage_bytes, file_count = repo.storage_stats(settings.local_store_path)
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
    )


@router.get("/login")
async def login_get(request: Request, user: OptionalUser):
    if user:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, None, "login.html")


@router.post("/login")
async def login_post(
    request: Request,
    session: SessionDep,
    tenant_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    try:
        body = LoginRequest(tenant_name=tenant_name, email=email, password=password)
    except ValidationError:
        return _render(request, None, "login.html", error="Check your inputs and try again.")

    tenant = await TenantRepository(session).get_by_name(body.tenant_name)
    if not tenant:
        return _render(request, None, "login.html", error="Invalid credentials.")
    user_repo = UserRepository(session, tenant.id)
    user = await user_repo.get_by_email(body.email)
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        return _render(request, None, "login.html", error="Invalid credentials.")

    await AuditRepository(session, tenant.id).record(
        user_id=user.id,
        action="login",
        resource_type="session",
        method="POST",
        path="/login",
        status_code=200,
    )
    await session.commit()

    token = create_access_token(user_id=user.id, tenant_id=tenant.id)
    response = RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    _set_session(response, token)
    return response


@router.get("/register")
async def register_get(request: Request, user: OptionalUser):
    if user:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, None, "register.html")


@router.post("/register")
async def register_post(
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
        role="admin",
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
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/patients/ui")
async def patients_list(request: Request, session: SessionDep, user: OptionalUser):
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


@router.post("/patients/ui")
async def patient_new_post(
    request: Request,
    session: SessionDep,
    mrn: str = Form(...),
    given_name: str = Form(...),
    family_name: str = Form(...),
    sex: str = Form(""),
    date_of_birth: str = Form(""),
):
    user = await get_optional_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    dob: date | None = None
    if date_of_birth:
        try:
            dob = date.fromisoformat(date_of_birth)
        except ValueError:
            return _render(
                request, user, "patient_new.html", error="Date of birth must be YYYY-MM-DD."
            )

    try:
        body = PatientCreate(
            mrn=mrn,
            given_name=given_name,
            family_name=family_name,
            sex=sex or None,
            date_of_birth=dob,
        )
    except ValidationError as exc:
        msg = exc.errors()[0]["msg"] if exc.errors() else "Invalid input"
        return _render(request, user, "patient_new.html", error=msg)

    patient = Patient(
        tenant_id=user.tenant_id,
        mrn=body.mrn,
        given_name=body.given_name,
        family_name=body.family_name,
        date_of_birth=body.date_of_birth,
        sex=body.sex,
        demographics=body.demographics,
    )
    repo = PatientRepository(session, user.tenant_id)
    try:
        await repo.add(patient)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        user = await get_optional_user(request, session)
        return _render(
            request, user, "patient_new.html", error="A patient with that MRN already exists."
        )

    return RedirectResponse(
        f"/patients/ui/{patient.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/patients/ui/{patient_id}")
async def patient_detail(
    request: Request,
    session: SessionDep,
    user: OptionalUser,
    patient_id: uuid.UUID,
):
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        return RedirectResponse(
            "/patients/ui?missing=1", status_code=status.HTTP_303_SEE_OTHER
        )
    documents = await DocumentRepository(session, user.tenant_id).list_for_patient(patient_id)
    return _render(
        request,
        user,
        "patient_detail.html",
        patient=patient,
        documents=documents,
        has_pending=any(d.ocr_status == "pending" for d in documents),
    )


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
async def document_viewer(
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
    return _render(request, user, "document_viewer.html", document=doc)


@router.get("/documents/ui/{document_id}/text-partial")
async def document_text_partial(
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


@router.post("/patients/ui/{patient_id}/documents")
async def upload_document_web(
    request: Request,
    session: SessionDep,
    background: BackgroundTasks,
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
    if mime not in _ALLOWED_MIME:
        return await _render_panel(f"Unsupported file type: {mime or 'unknown'}")

    data = await file.read()
    if len(data) == 0:
        return await _render_panel("File is empty.")
    if len(data) > _MAX_BYTES:
        return await _render_panel("File exceeds 25 MB limit.")

    store = get_document_store()
    file_key, file_hash = await store.put(tenant_id=user.tenant_id, data=data)

    existing = await repo.get_by_hash(patient_id, file_hash)
    if existing is None:
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
        background.add_task(process_document, doc.id, user.tenant_id)

    return await _render_panel()
