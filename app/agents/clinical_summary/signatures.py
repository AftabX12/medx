from __future__ import annotations

import dspy


class ClinicalSummarySig(dspy.Signature):
    """Write a clinical summary for the treating physician.
    This should read like a good handoff note — concise, contextual, and action-oriented.
    Clinicians are busy. Lead with what matters. Include trends, not just latest values.
    Mention anything flagged for review and how it was resolved."""

    patient_context: dict = dspy.InputField(
        desc="Full patient record: demographics, active problems, medications, allergies, recent observations"
    )
    recent_changes: dict = dspy.InputField(
        desc="What the Data Steward added or updated from the new document"
    )
    trends: dict = dspy.InputField(
        desc="Trends detected across historical values (e.g. HbA1c rising over 2 years)"
    )
    resolved_flags: list[dict] = dspy.InputField(
        desc="Flags that were raised and the clinician's resolution decisions"
    )

    active_issues: str = dspy.OutputField(
        desc="Current active problems with trend context. 2–4 sentences."
    )
    whats_new: str = dspy.OutputField(
        desc="What changed from this specific document. 1–3 sentences."
    )
    watch_list: str = dspy.OutputField(
        desc="Values or patterns that need physician attention. Bullet points."
    )
    background: str = dspy.OutputField(
        desc="Stable context: age, sex, known conditions, current medications. 1–2 sentences."
    )
    full_narrative: str = dspy.OutputField(
        desc=(
            "Complete paragraph summary combining all above. 100–200 words. "
            "What the doctor needs to know before walking into the room."
        )
    )
