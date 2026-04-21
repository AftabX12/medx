"""VLM OCR via OpenRouter (default: Qwen2.5-VL-72B:free). Rasterizes PDFs per page."""

from __future__ import annotations

import asyncio
import io

from app.ai.client import ImageInput, OpenRouterClient, get_ai_client
from app.ai.errors import RateLimitExhausted
from app.ai.models import ModelRole
from app.config import get_settings
from app.ingestion.ocr.engine import OCRPage, OCRResult
from app.logging import get_logger

log = get_logger(__name__)

_VISION_SYSTEM = (
    "You are an OCR engine for medical documents. Return ALL visible text verbatim, "
    "preserving reading order and line breaks. Render tables as tab-separated values. "
    "Do not summarize or omit any value. If a region is illegible, write [illegible]."
)
_VISION_USER = (
    "Extract all text from this page. Preserve numeric values and units exactly as printed."
)


def _rasterize_pdf_sync(data: bytes, dpi: int, max_pages: int) -> list[bytes]:
    """PDF bytes -> list[PNG bytes], capped at max_pages. Runs in a thread."""
    from pdf2image import convert_from_bytes

    images = convert_from_bytes(data, dpi=dpi, last_page=max_pages)
    out: list[bytes] = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


class OpenRouterVisionEngine:
    name = "openrouter_vision"

    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self._client = client
        self._settings = get_settings()

    @property
    def client(self) -> OpenRouterClient:
        return self._client or get_ai_client()

    def supports(self, mime: str) -> bool:
        return mime == "application/pdf" or mime.startswith("image/")

    async def extract(self, data: bytes, mime: str) -> OCRResult:
        try:
            if mime == "application/pdf":
                images = await asyncio.to_thread(
                    _rasterize_pdf_sync, data, 200, self._settings.ocr_max_pages
                )
                image_mime = "image/png"
            else:
                images = [data]
                image_mime = mime

            pages: list[OCRPage] = []
            for i, img_bytes in enumerate(images, start=1):
                resp = await self.client.complete_text(
                    role=ModelRole.VISION_OCR,
                    system=_VISION_SYSTEM,
                    user=_VISION_USER,
                    images=[ImageInput(data=img_bytes, mime=image_mime)],
                    temperature=0.0,
                    max_tokens=4096,
                )
                pages.append(OCRPage(page_num=i, text=(resp.content or "").strip()))

            text = "\n\n".join(p.text for p in pages if p.text)
            return OCRResult(
                text=text,
                pages=pages,
                engine=self.name,
                status="ok" if text else "no_text",
            )
        except RateLimitExhausted as exc:
            log.warning("vision_ocr_rate_limited", error=str(exc))
            return OCRResult(
                text="", engine=self.name, status="failed", error="rate_limited"
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("vision_ocr_failed", error=str(exc))
            return OCRResult(
                text="", engine=self.name, status="failed", error=str(exc)
            )
