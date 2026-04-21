"""Single unified extractor for all document types.

Adding a new document type requires only:
  1. A new DocType enum value in doctype.py
  2. A new entry in _CONFIGS below (system prompt + schema name)
  3. A JSON schema file in app/ai/schemas/
"""

from __future__ import annotations

from app.ai.agents.doctype import DocType
from app.ai.client import OpenRouterClient, get_ai_client
from app.ai.models import ModelRole
from app.ai.schemas import load_schema

_CONFIGS: dict[DocType, tuple[str, str]] = {
    DocType.LAB_PANEL: (
        "lab_panel",
        (
            "You extract structured lab results from medical lab reports. For every observation, "
            "capture label, numeric value (as a number), unit, reference_range if printed, and "
            "an abnormal_flag (H/L/HH/LL/null). Include a LOINC hint only if obvious (e.g. "
            "'2093-3' for total cholesterol). Confidence is your certainty in the row (0..1). "
            "Return JSON matching the LabPanel schema; omit anything you cannot read."
        ),
    ),
    DocType.IMAGING_REPORT: (
        "imaging_report",
        (
            "You extract structured data from cardiology imaging reports (echo, CT, cath, MRI). "
            "Capture modality, study_date, impression, and any numeric measurements "
            "(LVEF %, LVEDD, aortic root diameter, etc.) with units. "
            "Return JSON matching the ImagingReport schema."
        ),
    ),
    DocType.DISCHARGE_SUMMARY: (
        "discharge_summary",
        (
            "You extract structured data from hospital discharge summaries. Capture admission "
            "and discharge dates, the final diagnoses list, the discharge medications (name, "
            "dose, frequency, route, status), and any numeric observations with units "
            "(e.g. EF on discharge). Return JSON matching the DischargeSummary schema."
        ),
    ),
    DocType.MED_LIST: (
        "med_list",
        (
            "You extract structured medications from a med list. For each med, capture name, "
            "dose (with units if printed), frequency, route, and status (active/discontinued/held). "
            "Return JSON matching the MedList schema."
        ),
    ),
    DocType.HISTORY_PHYSICAL: (
        "history_physical",
        """You extract structured clinical data from History & Physical (H&P) examination notes.

Extract ALL of the following if present:
- chief_complaint: the patient's main reason for the visit (brief string)
- visit_date: date of the encounter (ISO format or null)
- vital_signs: BP, pulse, respirations, temperature, O2 sat, weight, height — each as {label, value, unit}
  - For blood pressure use value as string e.g. "168/98", unit "mmHg"
  - For pulse use numeric value, unit "bpm"
- problems: every condition mentioned in the problem list, assessment, past medical history,
  or review of systems — each as {label, status ("active"/"historical"/"resolved"), icd10_hint}
  - Include both acute and chronic problems
  - Past surgical history items should have status "historical"
- medications: ALL medications mentioned — current, past, OTC, and those in the plan —
  each as {name, dose, frequency, route, status ("active"/"planned"/"historical")}
- allergies: all drug/food/environmental allergies — each as {substance, reaction, severity}
- assessment: brief free-text clinical assessment/impression (1-3 sentences max)
- plan: brief free-text plan summary (1-3 sentences max)

Return JSON matching the schema. Include everything; do not omit problems or medications.""",
    ),
}


async def extract_document(
    doc_type: DocType,
    text: str,
    *,
    client: OpenRouterClient | None = None,
) -> dict:
    """Extract structured data from document text for the given doc_type.

    Raises KeyError if doc_type has no registered extractor config.
    """
    schema_name, system_prompt = _CONFIGS[doc_type]
    c = client or get_ai_client()
    resp = await c.complete_json(
        role=ModelRole.EXTRACT,
        system=system_prompt,
        user=text,
        schema=load_schema(schema_name),
        temperature=0.0,
        max_tokens=4096,
    )
    return resp.content


def supported_doc_types() -> frozenset[DocType]:
    """Return the set of DocTypes that have a registered extractor."""
    return frozenset(_CONFIGS.keys())
