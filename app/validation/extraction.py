"""JSON schema validation of LLM extraction output before DB write."""

from __future__ import annotations

from app.ai.schemas import load_schema

_DOC_TYPE_TO_SCHEMA = {
    "lab_panel": "lab_panel",
    "imaging_report": "imaging_report",
    "discharge_summary": "discharge_summary",
    "med_list": "med_list",
    "history_physical": "history_physical",
}


class ValidationError(ValueError):
    """Raised when an LLM extraction payload fails schema validation."""


def validate_extraction_output(doc_type: str, payload: dict) -> None:
    """Raise ValidationError if payload does not conform to its JSON schema.

    Silently passes for doc_types with no registered schema (e.g. "other").
    """
    schema_name = _DOC_TYPE_TO_SCHEMA.get(doc_type)
    if schema_name is None:
        return

    import jsonschema

    schema = load_schema(schema_name)
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise ValidationError(
            f"Extraction payload for {doc_type!r} failed schema check: {exc.message}"
        ) from exc
