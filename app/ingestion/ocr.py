"""Text extraction for uploaded documents.

Phase 1b covers text-based PDFs via pypdf. Scanned PDFs and images land in
`ocr_status = unsupported` for now — we'll add a proper OCR engine (Tesseract
or docTR) once we actually have non-text PDFs to process.
"""

from __future__ import annotations

import asyncio
import io
import uuid

import pypdf

from app.db.models import Document
from app.db.session import SessionLocal
from app.ingestion.store import get_document_store
from app.logging import get_logger

log = get_logger(__name__)


def _extract_pdf_text_sync(data: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(data))
    chunks: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        text = text.strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks)


async def process_document(document_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Runs after upload to populate `ocr_status` and `ocr_text`."""
    store = get_document_store()
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None or doc.tenant_id != tenant_id:
            return

        status = "failed"
        text: str | None = None
        try:
            if doc.mime_type == "application/pdf":
                with store.open(tenant_id=tenant_id, file_key=doc.file_key) as fh:
                    data = fh.read()
                text = await asyncio.to_thread(_extract_pdf_text_sync, data)
                status = "ok" if text else "no_text"
            else:
                # Images: proper OCR not wired yet.
                status = "unsupported"
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
        await session.commit()
