"""Dynamic two-step extraction for unrecognized document types.

Step 1 (plan): LLM reads the document, identifies what kind it is, and
writes a tailored extraction prompt for step 2.

Step 2 (extract): LLM uses that prompt to pull structured data from
the document as JSON.

Returns (doc_type_label, payload) where doc_type_label is a free-form
snake_case string (e.g. "pharmacy_receipt", "referral_letter") and
payload is arbitrary JSON. Internal metadata keys are prefixed with "_".
"""

from __future__ import annotations

from app.ai.client import OpenRouterClient, get_ai_client
from app.ai.models import ModelRole

_PLAN_SYSTEM = """\
You are a medical document analyst. Given a document, you must:
1. Identify exactly what kind of document it is — be specific (e.g. "pharmacy_receipt",
   "referral_letter", "insurance_card", "op_note", "prescription", "consent_form",
   "pathology_report", "vaccination_record"). Use snake_case.
2. Decide what structured information is worth extracting from it.
3. Write a precise extraction prompt instructing the LLM to return a JSON object
   with clearly named fields. Define those fields in the "fields" list.

Return JSON:
{
  "doc_type_label": "snake_case_type_name",
  "description": "one sentence describing this document",
  "extraction_prompt": "full system prompt for the extraction step",
  "fields": [{"name": "field_name", "type": "string|number|array|object", "description": "..."}]
}"""

_EXTRACT_SYSTEM_TEMPLATE = """\
{extraction_prompt}

Return a JSON object. Include only fields you can read from the document. \
Do not guess or invent values."""


async def plan_and_extract(
    text: str,
    *,
    client: OpenRouterClient | None = None,
) -> tuple[str, dict]:
    """Dynamically plan and extract data from an unrecognized document.

    Returns (doc_type_label, payload). The payload contains the extracted
    fields plus internal metadata keys prefixed with "_" (description,
    field definitions) so the document viewer can render them cleanly.
    """
    c = client or get_ai_client()
    snippet = text[:8000]

    # Step 1 — plan: identify doc type and generate extraction prompt
    plan_resp = await c.complete_json(
        role=ModelRole.EXTRACT,
        system=_PLAN_SYSTEM,
        user=f"Analyze this document and plan the extraction:\n\n{snippet}",
        temperature=0.0,
        max_tokens=1024,
    )
    plan = plan_resp.content if isinstance(plan_resp.content, dict) else {}

    doc_type_label = (
        (plan.get("doc_type_label") or "unknown_document")
        .lower()
        .replace(" ", "_")
    )
    extraction_prompt = (
        plan.get("extraction_prompt")
        or "Extract all key information from this document as structured JSON."
    )

    # Step 2 — extract: use the generated prompt to pull structured data
    extract_resp = await c.complete_json(
        role=ModelRole.EXTRACT,
        system=_EXTRACT_SYSTEM_TEMPLATE.format(extraction_prompt=extraction_prompt),
        user=snippet,
        temperature=0.0,
        max_tokens=2048,
    )
    payload = extract_resp.content if isinstance(extract_resp.content, dict) else {}

    # Attach plan metadata so the viewer can display context without re-querying
    payload["_doc_type_label"] = doc_type_label
    payload["_description"] = plan.get("description", "")
    payload["_fields"] = plan.get("fields", [])

    return doc_type_label, payload
