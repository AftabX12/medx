"""Document REST API — upload, retrieval, SSE pipeline events, and OCR text."""
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.db.models import Document
from app.db.repositories.document import DocumentRepository
from app.db.repositories.patient import PatientRepository
from app.deps import CurrentUser, SessionDep
from app.ingestion.store import get_document_store
from app.queue import get_queue
from app.schemas.document import DocumentResponse

router = APIRouter(tags=["documents"])

_ALLOWED_MIME = {
    "application/pdf": "pdf",
    "image/png": "image",
    "image/jpeg": "image",
    "image/jpg": "image",
}
_MAX_BYTES = 25 * 1024 * 1024  # 25 MB


@router.post(
    "/patients/{patient_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    patient_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    file: UploadFile = File(...),
    source_type: str = "upload",
) -> Document:
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient not found")

    mime = (file.content_type or "").lower()
    if mime not in _ALLOWED_MIME:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported type: {mime or 'unknown'}",
        )

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="empty file")
    if len(data) > _MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file larger than {_MAX_BYTES} bytes",
        )

    store = get_document_store()
    file_key, file_hash = await store.put(tenant_id=user.tenant_id, data=data)

    repo = DocumentRepository(session, user.tenant_id)
    existing = await repo.get_by_hash(patient_id, file_hash)
    if existing:
        return existing

    doc = Document(
        tenant_id=user.tenant_id,
        patient_id=patient_id,
        source_type=source_type,
        file_key=file_key,
        file_hash=file_hash,
        original_filename=file.filename,
        mime_type=mime,
        ocr_status="pending",
    )
    await repo.add(doc)
    await session.commit()
    await session.refresh(doc)
    queue = get_queue()
    await queue.enqueue("ocr_process", document_id=doc.id, tenant_id=user.tenant_id)
    return doc


@router.get(
    "/patients/{patient_id}/documents",
    response_model=list[DocumentResponse],
)
async def list_patient_documents(
    patient_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    limit: int = 100,
    offset: int = 0,
) -> list[Document]:
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient not found")
    repo = DocumentRepository(session, user.tenant_id)
    return await repo.list_for_patient(patient_id, limit=limit, offset=offset)


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> Document:
    doc = await DocumentRepository(session, user.tenant_id).get(document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    return doc


@router.get("/documents/{document_id}/text", response_class=PlainTextResponse)
async def document_text(
    document_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> str:
    doc = await DocumentRepository(session, user.tenant_id).get(document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    return doc.ocr_text or ""


@router.get("/documents/{document_id}/raw")
async def download_document(
    document_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> StreamingResponse:
    doc = await DocumentRepository(session, user.tenant_id).get(document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    store = get_document_store()
    fh = store.open(tenant_id=user.tenant_id, file_key=doc.file_key)
    headers = {}
    if doc.original_filename:
        headers["Content-Disposition"] = f'inline; filename="{doc.original_filename}"'
    return StreamingResponse(fh, media_type=doc.mime_type or "application/octet-stream", headers=headers)
