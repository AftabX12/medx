from __future__ import annotations

from time import perf_counter

import dspy

from app.agents.chat.signatures import ChatSig
from app.agents.chat.tools import (
    get_allergies,
    get_medications,
    get_observations,
    get_patient_demographics,
    get_patient_summary,
    get_pending_flags,
    get_problems,
    reset_tool_context,
    search_clinic_patients,
    set_tool_context,
)
from app.agents.run_logging import log_agent_run


class ChatAgent(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.answer = dspy.ReAct(
            ChatSig,
            tools=[
                get_patient_summary,
                get_observations,
                get_medications,
                get_problems,
                get_allergies,
                get_pending_flags,
                search_clinic_patients,
                get_patient_demographics,
            ],
            max_iters=8,
        )

    async def forward(self, question: str, patient_id: str, tenant_id: str) -> str:
        start = perf_counter()
        token = set_tool_context(tenant_id=tenant_id)
        try:
            scoped_question = f"{question}\n\nTenant ID for clinic-wide searches: {tenant_id}"
            result = await self.answer.aforward(question=scoped_question, patient_id=patient_id)
            await log_agent_run(
                tenant_id=tenant_id,
                document_id=None,
                agent_name="chat",
                inputs_snapshot={"question": question, "patient_id": patient_id},
                outputs_snapshot={
                    "answer": result.answer,
                    "data_used": getattr(result, "data_used", []),
                },
                tool_calls=_tool_calls_from_trajectory(getattr(result, "trajectory", {})),
                duration_ms=int((perf_counter() - start) * 1000),
                success=True,
            )
            return result.answer
        except Exception as exc:
            await log_agent_run(
                tenant_id=tenant_id,
                document_id=None,
                agent_name="chat",
                inputs_snapshot={"question": question, "patient_id": patient_id},
                outputs_snapshot={"error": str(exc)},
                tool_calls=[],
                duration_ms=int((perf_counter() - start) * 1000),
                success=False,
            )
            raise
        finally:
            reset_tool_context(token)


def _tool_calls_from_trajectory(trajectory: dict) -> list[dict]:
    calls = []
    idx = 0
    while f"tool_name_{idx}" in trajectory:
        calls.append(
            {
                "tool_name": trajectory.get(f"tool_name_{idx}"),
                "tool_args": trajectory.get(f"tool_args_{idx}") or {},
                "observation": trajectory.get(f"observation_{idx}"),
            }
        )
        idx += 1
    return calls
