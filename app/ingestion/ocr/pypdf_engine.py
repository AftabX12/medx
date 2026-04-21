"""Text-layer extraction via pypdf. First-pass engine for digital PDFs."""

from __future__ import annotations

import asyncio
import io

import pypdf

from app.ingestion.ocr.engine import OCRPage, OCRResult


def _extract_sync(data: bytes) -> list[OCRPage]:
    reader = pypdf.PdfReader(io.BytesIO(data))
    pages: list[OCRPage] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        pages.append(OCRPage(page_num=i, text=text.strip()))
    return pages


class PyPDFEngine:
    name = "pypdf"

    def supports(self, mime: str) -> bool:
        return mime == "application/pdf"

    async def extract(self, data: bytes, mime: str) -> OCRResult:
        pages = await asyncio.to_thread(_extract_sync, data)
        text = "\n\n".join(p.text for p in pages if p.text)
        return OCRResult(
            text=text,
            pages=pages,
            engine=self.name,
            status="ok" if text else "no_text",
        )
