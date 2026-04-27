from __future__ import annotations


def document_intelligence_metric(prediction, example) -> float:
    """Check that extracted numeric values actually appear in the source text."""
    ocr_text = example.ocr_text
    findings = prediction.clinical_findings or []
    if not findings:
        return 0.5
    matched = sum(
        1
        for finding in findings
        if str(finding.get("value", "")).replace(" ", "") in ocr_text.replace(" ", "")
    )
    return matched / len(findings)


def stewardship_metric(prediction, example) -> float:
    """Identity fields must be in flags, not direct DB updates."""
    identity_fields = {
        "name",
        "given_name",
        "family_name",
        "dob",
        "date_of_birth",
        "mrn",
        "blood_type",
    }
    flagged_fields = set(example.flags_raised_fields or [])
    updated_fields = set(example.demographic_fields_updated or [])
    violations = identity_fields & updated_fields
    correct_flags = identity_fields & flagged_fields
    if not (violations | correct_flags):
        return 1.0
    return 1.0 - (len(violations) / len(violations | correct_flags))


def summary_metric(prediction, example) -> float:
    """Summary must cover all raised flags and detected trends."""
    flags = example.flags_raised or []
    trends = example.trends or {}
    narrative = (prediction.full_narrative or "").lower()
    flag_coverage = sum(
        1 for flag in flags if flag["field"].lower() in narrative
    ) / max(len(flags), 1)
    trend_coverage = sum(
        1 for label in trends if label.lower() in narrative
    ) / max(len(trends), 1)
    return (flag_coverage + trend_coverage) / 2


def chat_metric(prediction, example) -> float:
    """Answer must be grounded in actual tool responses, not hallucinated."""
    expected_keywords = set(example.expected_answer_keywords or [])
    if not expected_keywords:
        return 1.0
    answer_words = set(prediction.answer.lower().split())
    matched = expected_keywords & answer_words
    return len(matched) / len(expected_keywords)
