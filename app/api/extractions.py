"""Extractions REST API — retrieve AI extraction results for a document."""
import uuid

from fastapi import APIRouter, HTTPException, status

from app.db.repositories.document import DocumentRepository
from app.db.repositories.extraction import ExtractionRepository
from app.db.repositories.patient import PatientRepository
from app.db.repositories.reconcile import ReconcileFlagRepository
from app.deps import CurrentUser, SessionDep
from app.queue import get_queue
from app.schemas.extraction import ExtractionResponse, ReconcileFlagResponse

router = APIRouter(tags=["extractions"])


@router.get(
    "/documents/{document_id}/extractions",
    response_model=list[ExtractionResponse],
)
async def list_document_extractions(
    document_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
):
    doc = await DocumentRepository(session, user.tenant_id).get(document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    return await ExtractionRepository(session, user.tenant_id).list_for_document(document_id)


@router.post(
    "/documents/{document_id}/reprocess",
    status_code=status.HTTP_202_ACCEPTED,
)
async def reprocess_document(
    document_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> dict:
    doc = await DocumentRepository(session, user.tenant_id).get(document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    queue = get_queue()
    await queue.enqueue(
        "extract_document", document_id=doc.id, tenant_id=user.tenant_id
    )
    return {"status": "enqueued"}


@router.get(
    "/patients/{patient_id}/reconcile-flags",
    response_model=list[ReconcileFlagResponse],
)
async def list_patient_reconcile_flags(
    patient_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    include_resolved: bool = False,
):
    patient = await PatientRepository(session, user.tenant_id).get(patient_id)
    if not patient:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient not found")
    repo = ReconcileFlagRepository(session, user.tenant_id)
    return await repo.list_for_patient(
        patient_id, resolved=None if include_resolved else False
    )
