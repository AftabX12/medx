"""Pre-LLM upload validation: MIME type, file size, and PDF integrity."""

from __future__ import annotations

import io

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
    4. PDF: readable and within page limit
    """
    mime = mime.lower()
    if mime not in ALLOWED_MIME:
        raise UploadRejected(f"Unsupported file type: {mime or 'unknown'}")

    if len(data) == 0:
        raise UploadRejected("File is empty.")

    if len(data) > MAX_BYTES:
        raise UploadRejected("File exceeds 25 MB limit.")

    if mime == "application/pdf":
        _validate_pdf(data)


def _validate_pdf(data: bytes) -> None:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    from app.config import get_settings

    try:
        reader = PdfReader(io.BytesIO(data))
        n_pages = len(reader.pages)
    except (PdfReadError, Exception):
        raise UploadRejected("PDF appears to be corrupt or unreadable.")

    max_pages = get_settings().ocr_max_pages
    if n_pages > max_pages:
        raise UploadRejected(
            f"PDF has {n_pages} pages; limit is {max_pages} pages."
        )
