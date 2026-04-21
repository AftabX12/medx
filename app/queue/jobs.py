"""Registered job handlers for the background worker queue.

Importing this module wires the named jobs into the InProcessQueue. Any new
background job must be added here and registered in `register_all`.

Job naming convention: snake_case verb_noun matching the queue job name string
used in `queue.enqueue("job_name", ...)` calls throughout the codebase.

Current jobs:
    ocr_process      — OCR a newly uploaded document (text extraction)
    extract_document — Full AI pipeline: classify → extract → persist → summarize
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
    """Run the full AI extraction pipeline for a document that has completed OCR.

    Delegates to run_extraction in app.ai.agents.router, which runs:
    classify → extract → persist → profile reconcile → summarize.

    The ImportError guard allows the queue to start even in environments where
    the AI dependencies are not installed (e.g. lightweight CI).
    """
    try:
        from app.ai.agents.router import run_extraction

        await run_extraction(document_id, tenant_id)
    except ImportError:
        log.info("extract_stub_skipped", document_id=str(document_id))


def register_all(queue) -> None:
    """Register all job handlers with the queue singleton.

    Called once at startup by get_queue() in asyncio_queue.py.
    Add new jobs here — do not call queue.register() from other modules.
    """
    queue.register("ocr_process", ocr_process)
    queue.register("extract_document", extract_document)
