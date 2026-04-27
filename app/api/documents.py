"""Document REST API — upload, retrieval, SSE pipeline events, and OCR text."""
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import Document, ReconcileFlag
from app.db.repositories.document import DocumentRepository
from app.db.repositories.patient import PatientRepository
from app.deps import CurrentUser, SessionDep
from app.ingestion.store import get_document_store
from app.queue import get_queue
from app.schemas.document import DocumentResponse
from app.validation.upload import MAX_BYTES as _MAX_BYTES

router = APIRouter(tags=["documents"])


class FlagResolutionRequest(BaseModel):
    choice: Literal["keep_existing", "use_new"]
    note: str | None = None

_ALLOWED_MIME = {
    "application/pdf": "pdf",
    "image/png": "image",
    "image/jpeg": "image",
    "image/jpg": "image",
}


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


@router.get("/api/documents/{document_id}/flags")
async def list_document_flags(
    document_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> list[dict]:
    doc = await DocumentRepository(session, user.tenant_id).get(document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    rows = (
        await session.execute(
            select(ReconcileFlag)
            .where(
                ReconcileFlag.tenant_id == user.tenant_id,
                ReconcileFlag.document_id == document_id,
                ReconcileFlag.resolved.is_(False),
            )
            .order_by(ReconcileFlag.created_at.desc())
        )
    ).scalars().all()
    return [_flag_payload(row) for row in rows]


@router.post("/api/flags/{flag_id}/resolve")
async def resolve_reconcile_flag(
    flag_id: uuid.UUID,
    body: FlagResolutionRequest,
    session: SessionDep,
    user: CurrentUser,
) -> dict:
    flag = await session.get(ReconcileFlag, flag_id)
    if not flag or flag.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="flag not found")

    flag.resolution_choice = body.choice
    flag.resolution_note = body.note
    flag.resolved = True
    flag.resolved_at = datetime.now(UTC)
    flag.resolved_by = str(user.id)
    await session.commit()
    await session.refresh(flag)
    return _flag_payload(flag)


@router.post("/api/documents/{document_id}/resume")
async def resume_document_pipeline(
    document_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> dict:
    doc = await DocumentRepository(session, user.tenant_id).get(document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")

    flags = (
        await session.execute(
            select(ReconcileFlag)
            .where(
                ReconcileFlag.tenant_id == user.tenant_id,
                ReconcileFlag.document_id == document_id,
            )
            .order_by(ReconcileFlag.created_at.asc())
        )
    ).scalars().all()
    unresolved = [flag for flag in flags if not flag.resolved]
    if unresolved:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{len(unresolved)} flag(s) still unresolved",
        )

    decisions = [
        {
            "flag_id": str(flag.id),
            "choice": flag.resolution_choice or "keep_existing",
            "note": flag.resolution_note,
        }
        for flag in flags
    ]

    from app.agents.graph import get_compiled_graph

    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": str(document_id)}}
    await graph.ainvoke(Command(resume=decisions), config)
    return {"status": "resumed", "decisions": len(decisions)}


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


def _flag_payload(flag: ReconcileFlag) -> dict:
    return {
        "id": str(flag.id),
        "patient_id": str(flag.patient_id),
        "document_id": str(flag.document_id),
        "kind": flag.kind,
        "resource_type": flag.resource_type,
        "field": flag.details.get("field"),
        "current_value": flag.details.get("existing_value") or flag.details.get("existing"),
        "new_value": flag.details.get("document_value") or flag.details.get("new"),
        "details": flag.details,
        "severity": flag.severity,
        "agent_reasoning": flag.agent_reasoning,
        "resolution_options": flag.resolution_options,
        "resolution_choice": flag.resolution_choice,
        "resolution_note": flag.resolution_note,
        "resolved": flag.resolved,
        "resolved_at": flag.resolved_at.isoformat() if flag.resolved_at else None,
    }
