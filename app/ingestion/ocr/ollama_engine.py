"""VLM OCR via Ollama local API. Requires a multimodal model (e.g. gemma4, llava)."""

from __future__ import annotations

import asyncio
import io

from app.ai.client import ImageInput, OpenRouterClient
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


def _rasterize_pdf_sync(data: bytes, dpi: int) -> list[bytes]:
    from pdf2image import convert_from_bytes

    images = convert_from_bytes(data, dpi=dpi)
    out: list[bytes] = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


class OllamaVisionEngine:
    """OCR via Ollama local VLM. Uses ollama_model, independent of AI_PROVIDER."""

    name = "ollama_vision"

    def __init__(self) -> None:
        settings = get_settings()
        # Use OLLAMA_VISION_MODEL if set; fall back to OLLAMA_MODEL.
        vision_model = settings.ollama_vision_model or settings.ollama_model
        # Dedicated client pinned to ollama with the vision model, regardless of AI_PROVIDER.
        self._client = OpenRouterClient(force_provider="ollama", force_model=vision_model)

    def supports(self, mime: str) -> bool:
        return mime == "application/pdf" or mime.startswith("image/")

    async def extract(self, data: bytes, mime: str) -> OCRResult:
        try:
            if mime == "application/pdf":
                images = await asyncio.to_thread(_rasterize_pdf_sync, data, 150)
                image_mime = "image/png"
            else:
                images = [data]
                image_mime = mime

            # Process pages in parallel for better performance
            async def process_page(i: int, img_bytes: bytes) -> OCRPage:
                resp = await self._client.complete_text(
                    role=ModelRole.VISION_OCR,
                    system=_VISION_SYSTEM,
                    user=_VISION_USER,
                    images=[ImageInput(data=img_bytes, mime=image_mime)],
                    temperature=0.0,
                    max_tokens=4096,
                )
                return OCRPage(page_num=i, text=(resp.content or "").strip())

            # Limit concurrency to avoid overwhelming the Ollama server
            import asyncio
            semaphore = asyncio.Semaphore(2)  # Process 2 pages at a time
            
            async def process_with_limit(i: int, img_bytes: bytes) -> OCRPage:
                async with semaphore:
                    return await process_page(i, img_bytes)
            
            tasks = [process_with_limit(i, img) for i, img in enumerate(images, start=1)]
            pages = await asyncio.gather(*tasks)

            text = "\n\n".join(p.text for p in pages if p.text)
            return OCRResult(
                text=text,
                pages=pages,
                engine=self.name,
                status="ok" if text else "no_text",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("ollama_ocr_failed", error=str(exc))
            return OCRResult(
                text="", engine=self.name, status="failed", error=str(exc)
            )
