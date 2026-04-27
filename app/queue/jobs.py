"""Registered job handlers for the background worker queue.

Importing this module wires the named jobs into the InProcessQueue. Any new
background job must be added here and registered in `register_all`.

Job naming convention: snake_case verb_noun matching the queue job name string
used in `queue.enqueue("job_name", ...)` calls throughout the codebase.

Current jobs:
    ocr_process      — OCR a newly uploaded document (text extraction)
    extract_document — Full agentic pipeline: understand → steward → summarize
"""

from __future__ import annotations

import uuid

from app.logging import get_logger

log = get_logger(__name__)


async def ocr_process(*, document_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Run OCR on a document and write the extracted text to Document.ocr_text.

    Tries pypdf (text-layer PDF) first, then OpenRouter vision VLM for scanned
    documents, then local Marker as a final fallback. Sets ocr_status to "ok",
    "failed", "no_text", or "unsupported" on completion and enqueues
    `extract_document` automatically on success.
    """
    from app.ingestion.ocr import process_document

    await process_document(document_id, tenant_id)


async def extract_document(*, document_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Run the full AI pipeline via the LangGraph graph.

    Routes through: document_intelligence → data_steward → clinical_summary.
    State is checkpointed so the graph can resume on server restart.
    """
    from app.agents.graph import get_compiled_graph
    from app.agents.state import PipelineState
    from app.db.models import Document
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None or doc.tenant_id != tenant_id:
            log.warning("extract_document_skipped", document_id=str(document_id), reason="not found or tenant mismatch")
            return
        ocr_text = doc.ocr_text or ""
        patient_id = str(doc.patient_id)

    initial_state: PipelineState = {
        "document_id": str(document_id),
        "patient_id": patient_id,
        "tenant_id": str(tenant_id),
        "ocr_text": ocr_text,
        "events": [],
    }
    config = {"configurable": {"thread_id": str(document_id)}}
    graph = get_compiled_graph()
    await graph.ainvoke(initial_state, config)


def register_all(queue) -> None:
    """Register all job handlers with the queue singleton.

    Called once at startup by get_queue() in asyncio_queue.py.
    Add new jobs here — do not call queue.register() from other modules.
    """
    queue.register("ocr_process", ocr_process)
    queue.register("extract_document", extract_document)
