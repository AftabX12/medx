"""OCR pipeline orchestration. Persists ocr_status/ocr_text on the Document row.

Flow:
  1. PDF → try pypdf first; non-empty text wins (cheap, zero-call path).
  2. Otherwise (PDF with no text layer OR image): dispatch to the configured
     engine (openrouter_vision by default; marker for local fallback).
  3. On RateLimitExhausted from the vision engine, fall back to Marker if
     installed; else mark failed with error=rate_limited.
"""

from __future__ import annotations

import uuid

from app.config import get_settings
from app.db.models import Document
from app.db.session import SessionLocal
from app.events import get_event_bus
from app.ingestion.ocr.engine import OCREngine, OCRResult
from app.ingestion.ocr.openrouter_engine import OpenRouterVisionEngine
from app.ingestion.ocr.pypdf_engine import PyPDFEngine
from app.ingestion.store import get_document_store
from app.logging import get_logger

MIN_OCR_TEXT_CHARS = 20

log = get_logger(__name__)


def _resolve_engine(name: str) -> OCREngine:
    """Instantiate the named OCR engine; raises ValueError for unknown names."""
    if name == "openrouter_vision":
        return OpenRouterVisionEngine()
    if name == "marker":
        from app.ingestion.ocr.marker_engine import MarkerEngine

        return MarkerEngine()
    raise ValueError(f"unknown ocr_engine: {name}")


async def _ocr_bytes(data: bytes, mime: str) -> OCRResult:
    """Run OCR on raw file bytes, trying pypdf first for PDFs.

    Falls back from vision engine to local Marker if rate-limited.
    Returns an OCRResult with status "ok", "failed", "no_text", or "unsupported".
    """
    settings = get_settings()

    if mime == "application/pdf":
        pypdf_res = await PyPDFEngine().extract(data, mime)
        if pypdf_res.status == "ok" and pypdf_res.text:
            return pypdf_res

    engine = _resolve_engine(settings.ocr_engine)
    if not engine.supports(mime):
        return OCRResult(text="", engine=engine.name, status="unsupported")

    result = await engine.extract(data, mime)

    if (
        result.status == "failed"
        and result.error == "rate_limited"
        and settings.ocr_engine != "marker"
    ):
        try:
            from app.ingestion.ocr.marker_engine import MarkerEngine

            log.info("vision_fallback_to_marker")
            result = await MarkerEngine().extract(data, mime)
        except ImportError:
            log.warning("marker_not_installed_no_fallback")

    return result


async def process_document(document_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Upload → OCR. Populates `ocr_status` and `ocr_text` on the Document row.

    Chains to the extraction queue when status=='ok'; the extract handler is
    registered by app.queue.jobs and imported lazily to avoid a cycle.
    """
    store = get_document_store()
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None or doc.tenant_id != tenant_id:
            return

        from datetime import datetime, timezone
        ps0 = dict(doc.pipeline_status or {})
        ps0["ocr"] = {"status": "running", "ts": datetime.now(timezone.utc).isoformat(), "detail": ""}
        doc.pipeline_status = ps0
        await session.flush()
        await get_event_bus().emit(document_id, {"type": "step", "step": "ocr", "status": "running", "detail": ""})

        status = "failed"
        text: str | None = None
        try:
            with store.open(tenant_id=tenant_id, file_key=doc.file_key) as fh:
                data = fh.read()
            result = await _ocr_bytes(data, doc.mime_type)
            status = result.status
            text = result.text or None
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "ocr_failed",
                document_id=str(document_id),
                mime=doc.mime_type,
                error=str(exc),
            )
            status = "failed"

        doc.ocr_status = status
        doc.ocr_text = text
        from datetime import datetime, timezone
        ps = dict(doc.pipeline_status or {})
        ps["ocr"] = {"status": "ok" if status == "ok" else "failed", "ts": datetime.now(timezone.utc).isoformat(), "detail": status}
        doc.pipeline_status = ps
        await session.commit()

        await get_event_bus().emit(
            document_id,
            {"type": "step", "step": "ocr", "status": "ok" if status == "ok" else "failed", "detail": status},
        )

    if status == "ok":
        if not text or len(text.strip()) < MIN_OCR_TEXT_CHARS:
            log.info(
                "ocr_text_too_short_skip_extract",
                document_id=str(document_id),
                chars=len((text or "").strip()),
            )
            return
        try:
            from app.queue.asyncio_queue import get_queue

            queue = get_queue()
            await queue.enqueue(
                "extract_document", document_id=document_id, tenant_id=tenant_id
            )
        except Exception as exc:  # noqa: BLE001
            log.info("extract_enqueue_skipped", error=str(exc))
