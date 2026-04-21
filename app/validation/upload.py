"""Pre-LLM upload validation: MIME type, file size, PDF page count."""

from __future__ import annotations

from app.config import get_settings

ALLOWED_MIME = frozenset(
    {"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/tiff"}
)
MAX_BYTES = 25 * 1024 * 1024


class UploadRejected(ValueError):
    """Raised when an uploaded file fails deterministic pre-checks."""


def validate_upload(data: bytes, mime: str) -> None:
    """Raise UploadRejected if the file should not enter the pipeline.

    Checks (in order):
    1. MIME type in allowlist
    2. Non-empty
    3. Size ≤ MAX_BYTES
    4. PDF page count ≤ ocr_max_pages
    """
    mime = mime.lower()
    if mime not in ALLOWED_MIME:
        raise UploadRejected(f"Unsupported file type: {mime or 'unknown'}")

    if len(data) == 0:
        raise UploadRejected("File is empty.")

    if len(data) > MAX_BYTES:
        raise UploadRejected("File exceeds 25 MB limit.")

    if mime == "application/pdf":
        _check_pdf_pages(data)


def _check_pdf_pages(data: bytes) -> None:
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
    except Exception:  # noqa: BLE001 — malformed PDF
        raise UploadRejected("Could not read PDF; file may be corrupt.")

    max_pages = get_settings().ocr_max_pages
    if page_count > max_pages:
        raise UploadRejected(
            f"PDF has {page_count} pages; limit is {max_pages}."
        )
