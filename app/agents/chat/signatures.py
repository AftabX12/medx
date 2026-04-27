from __future__ import annotations

import dspy


class ChatSig(dspy.Signature):
    """Answer clinical questions about a patient or the clinic.
    Use the available tools to look up specific data before answering.
    Be concise and factual. Cite specific values (with dates) where relevant.
    Never invent data not returned by the tools."""

    question: str = dspy.InputField(desc="The clinician's or patient's question")
    patient_id: str = dspy.InputField(
        desc="Specific patient UUID to scope the answer, or 'clinic' for clinic-wide questions"
    )

    answer: str = dspy.OutputField(
        desc="Concise factual answer, 2–4 sentences unless a list is needed"
    )
    data_used: list[str] = dspy.OutputField(
        desc="List of data sources consulted to answer (e.g. 'HbA1c observations', 'medication list')"
    )
