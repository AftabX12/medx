"""Pre-LLM upload validation: MIME type and file size."""

from __future__ import annotations

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
    """
    mime = mime.lower()
    if mime not in ALLOWED_MIME:
        raise UploadRejected(f"Unsupported file type: {mime or 'unknown'}")

    if len(data) == 0:
        raise UploadRejected("File is empty.")

    if len(data) > MAX_BYTES:
        raise UploadRejected("File exceeds 25 MB limit.")
