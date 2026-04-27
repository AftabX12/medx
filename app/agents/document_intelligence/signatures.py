from __future__ import annotations

import dspy


class DocumentIntelligenceSig(dspy.Signature):
    """Analyze a medical document and extract everything clinically relevant.
    Do NOT use fixed categories. Describe what the document actually is.
    Extract all findings regardless of document type."""

    ocr_text: str = dspy.InputField(desc="Raw text extracted from the medical document via OCR")

    document_nature: str = dspy.OutputField(
        desc="Free-text description: what kind of document this is and where it is from"
    )
    clinical_domain: str = dspy.OutputField(
        desc="Medical domain covered (e.g. hematology, cardiology, pharmacy, primary care)"
    )
    observation_date: str | None = dspy.OutputField(
        desc="Date of the clinical encounter, test, or report in ISO format. Null if not found."
    )
    patient_identifiers: dict = dspy.OutputField(
        desc="Any patient name, DOB, MRN, address, phone, or insurance found in the document"
    )
    provider_info: dict = dspy.OutputField(
        desc="Ordering provider name, facility, NPI if present"
    )
    clinical_findings: list[dict] = dspy.OutputField(
        desc="All lab values, vitals, measurements. Each as {label, value, unit, reference_range, context}"
    )
    medications: list[dict] = dspy.OutputField(
        desc="All medications mentioned. Each as {name, dose, frequency, route, status}"
    )
    problems: list[dict] = dspy.OutputField(
        desc="All diagnoses, conditions, complaints. Each as {label, status, icd10_hint}"
    )
    allergies: list[dict] = dspy.OutputField(
        desc="All allergies. Each as {substance, reaction, severity}"
    )
    notable: str = dspy.OutputField(
        desc="What stands out clinically — abnormal values, patterns worth flagging, anything unusual"
    )
