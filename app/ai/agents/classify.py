"""Classify a document's OCR text into one of the DocType buckets."""

from __future__ import annotations

from app.ai.agents.doctype import DocType
from app.ai.client import OpenRouterClient, get_ai_client
from app.ai.models import ModelRole
from app.ai.schemas import load_schema

_SYSTEM = (
    "You are a clinical document classifier. Read the text and decide which category "
    "fits best. Categories:\n"
    "- lab_panel: a lab report with numeric analyte values (chemistry, hematology, lipids).\n"
    "- imaging_report: a radiology/echo/cath report with modality + impression.\n"
    "- discharge_summary: a hospital-stay summary with admission/discharge dates, "
    "diagnoses, and discharge medications.\n"
    "- med_list: a standalone medication list or reconciliation.\n"
    "- history_physical: a history & physical examination (H&P) with chief complaint, "
    "history of present illness, past medical history, physical exam findings, vital signs, "
    "review of systems, assessment, and/or plan. Also includes SOAP notes and clinic notes.\n"
    "- other: anything else not covered above.\n"
    "Return JSON: {\"doc_type\": <one of above>, \"confidence\": 0..1, \"rationale\": str}."
)


async def classify_document(
    text: str, *, client: OpenRouterClient | None = None
) -> tuple[DocType, float]:
    c = client or get_ai_client()
    snippet = text[:6000]
    resp = await c.complete_json(
        role=ModelRole.CLASSIFY,
        system=_SYSTEM,
        user=snippet,
        schema=load_schema("classify"),
        temperature=0.0,
        max_tokens=256,
    )
    payload = resp.content
    try:
        doc_type = DocType(payload["doc_type"])
    except (KeyError, ValueError):
        doc_type = DocType.OTHER
    confidence = float(payload.get("confidence", 0.0))
    return doc_type, confidence
