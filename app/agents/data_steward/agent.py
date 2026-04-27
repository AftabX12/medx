from __future__ import annotations

from typing import Any

import dspy

from app.agents.data_steward.signatures import StewardshipSig
from app.agents.data_steward.tools import (
    add_allergy,
    add_medication,
    add_observation,
    add_problem,
    get_observation_history,
    get_patient_record,
    raise_flag,
    reset_tool_context,
    set_tool_context,
    update_medication_status,
)
from app.agents.state import StewardshipResult


class PatientDataStewardAgent(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.reason = dspy.ReAct(
            StewardshipSig,
            tools=[
                get_patient_record,
                get_observation_history,
                add_observation,
                add_medication,
                update_medication_status,
                add_problem,
                add_allergy,
                raise_flag,
            ],
            max_iters=15,
        )

    async def forward(
        self,
        *,
        document_understanding: dict,
        patient_id: str,
        tenant_id: str,
        document_id: str,
    ) -> StewardshipResult:
        token = set_tool_context(tenant_id=tenant_id)
        try:
            current_patient_record = await get_patient_record(patient_id)
            enriched_understanding = dict(document_understanding)
            enriched_understanding.setdefault("patient_id", patient_id)
            enriched_understanding.setdefault("source_document_id", document_id)

            result = await self.reason.aforward(
                document_understanding=enriched_understanding,
                current_patient_record=current_patient_record,
            )
            actions_taken, flags_raised = _derive_trace_outputs(
                getattr(result, "trajectory", {})
            )
            return StewardshipResult(
                actions_taken=actions_taken,
                flags_raised=flags_raised,
                trends=getattr(result, "trends_noted", None) or {},
            )
        finally:
            reset_tool_context(token)


def _derive_trace_outputs(trajectory: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    actions_taken: list[dict] = []
    flags_raised: list[dict] = []

    idx = 0
    while f"tool_name_{idx}" in trajectory:
        tool_name = trajectory.get(f"tool_name_{idx}")
        tool_args = trajectory.get(f"tool_args_{idx}") or {}
        observation = trajectory.get(f"observation_{idx}")

        if tool_name == "raise_flag":
            flags_raised.append(
                {
                    "flag_id": str(observation or ""),
                    "field": str(tool_args.get("field", "")),
                    "severity": str(tool_args.get("severity", "")),
                    "reasoning": str(tool_args.get("reasoning", "")),
                }
            )
        elif tool_name in {
            "add_observation",
            "add_medication",
            "update_medication_status",
            "add_problem",
            "add_allergy",
        }:
            actions_taken.append(
                {
                    "action": str(tool_name),
                    "id": str(observation or ""),
                    "args": tool_args,
                }
            )

        idx += 1

    return actions_taken, flags_raised
