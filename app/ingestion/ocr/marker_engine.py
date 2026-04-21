"""Local fallback OCR via Marker (opt-in via the `ocr-local` extra).

Lazy-imports `marker` so a missing install only hurts when this engine is selected.
"""

from __future__ import annotations

import asyncio

from app.ingestion.ocr.engine import OCRPage, OCRResult
from app.logging import get_logger

log = get_logger(__name__)


def _extract_sync(data: bytes) -> tuple[str, list[OCRPage]]:
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered
    except ImportError as exc:  # noqa: BLE001
        raise RuntimeError(
            "Marker not installed. Install the 'ocr-local' extra: pip install '.[ocr-local]'"
        ) from exc

    import tempfile
    from pathlib import Path

    converter = PdfConverter(artifact_dict=create_model_dict())
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        rendered = converter(str(tmp_path))
        text, _, _ = text_from_rendered(rendered)
    finally:
        tmp_path.unlink(missing_ok=True)

    pages = [OCRPage(page_num=1, text=text.strip())] if text else []
    return text.strip(), pages


class MarkerEngine:
    name = "marker"

    def supports(self, mime: str) -> bool:
        return mime == "application/pdf"

    async def extract(self, data: bytes, mime: str) -> OCRResult:
        try:
            text, pages = await asyncio.to_thread(_extract_sync, data)
        except Exception as exc:  # noqa: BLE001
            log.warning("marker_failed", error=str(exc))
            return OCRResult(text="", engine=self.name, status="failed", error=str(exc))
        return OCRResult(
            text=text,
            pages=pages,
            engine=self.name,
            status="ok" if text else "no_text",
        )
