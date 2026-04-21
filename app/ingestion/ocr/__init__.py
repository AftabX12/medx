"""OCR package. Re-exports `process_document` for callers that import from the old path."""

from app.ingestion.ocr.engine import OCREngine, OCRPage, OCRResult
from app.ingestion.ocr.pipeline import process_document

__all__ = ["OCREngine", "OCRPage", "OCRResult", "process_document"]
