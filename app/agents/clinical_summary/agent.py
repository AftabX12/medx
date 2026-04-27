from __future__ import annotations

import dspy

from app.agents.clinical_summary.signatures import ClinicalSummarySig
from app.agents.clinical_summary.tools import (
    get_patient_full_context,
    get_recent_document_changes,
    reset_tool_context,
    set_tool_context,
)


class ClinicalSummaryAgent(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.write = dspy.ChainOfThought(ClinicalSummarySig)

    async def forward(
        self,
        patient_id: str,
        document_id: str,
        tenant_id: str,
        trends: dict,
        resolved_flags: list[dict],
    ) -> str:
        token = set_tool_context(tenant_id=tenant_id)
        try:
            patient_context = await get_patient_full_context(patient_id)
            recent_changes = await get_recent_document_changes(patient_id, document_id)
            result = await self.write.aforward(
                patient_context=patient_context,
                recent_changes=recent_changes,
                trends=trends,
                resolved_flags=resolved_flags,
            )
            return result.full_narrative
        finally:
            reset_tool_context(token)
