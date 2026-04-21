"""Extract patient demographics from a document header/footer regardless of document type.

Returns a dict of fields found; missing fields are omitted (not null) so callers
can distinguish "not in document" from "explicitly blank".
"""

from __future__ import annotations

from app.ai.client import get_ai_client
from app.ai.models import ModelRole

_SYSTEM = """You are extracting patient demographic information from a medical document.
Look in headers, footers, cover pages, and patient identification sections.
Return ONLY a JSON object with fields you can confidently read from the document.
Omit any field you cannot find or are unsure about — do not guess.
Return {} if no patient info is found."""

_USER = """Extract patient demographics from this document. Return a JSON object with any of these fields you find:
- given_name (first name only)
- family_name (last name / surname only)
- date_of_birth (ISO format YYYY-MM-DD if possible)
- sex (Male/Female/Other)
- mrn (medical record number / patient ID)
- phone
- email
- address_line1
- city
- state
- zip_code
- country
- blood_type
- insurance_provider
- insurance_id
- primary_physician
- allergies_summary (free text list of known allergies if stated)

Document text:
{text}"""


async def extract_patient_info(ocr_text: str) -> dict:
    """Return whatever patient demographics can be read from the document."""
    client = get_ai_client()
    try:
        resp = await client.complete_json(
            role=ModelRole.EXTRACT,
            system=_SYSTEM,
            user=_USER.format(text=ocr_text[:12000]),
            temperature=0.0,
            max_tokens=512,
        )
        data = resp.content
        if not isinstance(data, dict):
            return {}
        # Strip empty strings so callers see only real values
        return {k: v for k, v in data.items() if v not in (None, "", [], {})}
    except Exception:  # noqa: BLE001
        return {}
