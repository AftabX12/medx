from __future__ import annotations

from typing import Annotated, NotRequired, TypedDict


class DocumentUnderstanding(TypedDict):
    document_nature: str
    clinical_domain: str
    observation_date: str | None
    patient_identifiers: dict
    provider_info: dict
    clinical_findings: list[dict]
    medications: list[dict]
    problems: list[dict]
    allergies: list[dict]
    notable: str


class StewardshipResult(TypedDict):
    actions_taken: list[dict]
    flags_raised: list[dict]
    trends: dict


class FlagItem(TypedDict):
    flag_id: str
    field: str
    current_value: str
    new_value: str
    severity: str       # critical | warning | info
    reasoning: str


class HumanDecision(TypedDict):
    flag_id: str
    choice: str         # keep_existing | use_new
    note: str | None


class PipelineEvent(TypedDict):
    step: str
    status: str         # running | ok | failed | skipped
    detail: str


def add_events(left: list, right: list) -> list:
    return left + right


class PipelineState(TypedDict):
    # Inputs
    document_id: str
    patient_id: str
    tenant_id: str
    ocr_text: str

    # Agent outputs
    document_understanding: NotRequired[DocumentUnderstanding]
    stewardship_result: NotRequired[StewardshipResult]
    pending_flags: NotRequired[list[FlagItem]]

    # Human-in-the-loop
    human_review_pending: NotRequired[bool]
    human_decisions: NotRequired[list[HumanDecision]]

    # Final output
    clinical_summary: NotRequired[str]

    # Pipeline metadata
    events: Annotated[list[PipelineEvent], add_events]
    error: NotRequired[str]
