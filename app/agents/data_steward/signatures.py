from __future__ import annotations

import dspy


class StewardshipSig(dspy.Signature):
    """You manage a patient's medical record. You receive new findings extracted
    from a document and the patient's current record. Decide what to do with each piece of information.

    Rules you must follow:
    - Identity fields (name, DOB, MRN, blood type): ALWAYS call raise_flag. Never update these directly.
    - Clinical observations (lab values, vitals, measurements): ALWAYS call add_observation. These are time-series.
    - New medications: call add_medication.
    - Medication discontinued: call update_medication_status.
    - Medication dose change: call raise_flag (warning severity).
    - New diagnosis or problem: call add_problem.
    - Problem marked resolved: call raise_flag before any change.
    - Address, phone, email: call raise_flag with info severity.

    Use the tools provided. Call them one by one as needed."""

    document_understanding: dict = dspy.InputField(
        desc="Structured findings from the Document Intelligence Agent"
    )
    current_patient_record: dict = dspy.InputField(
        desc="Patient's current demographics, problems, medications, allergies, and recent observations"
    )
    actions_summary: str = dspy.OutputField(
        desc="Brief summary of what was added, updated, and flagged"
    )
    trends_noted: dict = dspy.OutputField(
        desc="Trends detected by comparing new values against historical values"
    )
