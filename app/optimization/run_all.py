from __future__ import annotations

import asyncio

import dspy
from sqlalchemy import select

from app.agents.clinical_summary.agent import ClinicalSummaryAgent
from app.agents.data_steward.agent import PatientDataStewardAgent
from app.agents.document_intelligence.agent import DocumentIntelligenceAgent
from app.db.models import AgentRunLog
from app.db.session import SessionLocal
from app.optimization.metrics import (
    document_intelligence_metric,
    stewardship_metric,
    summary_metric,
)
from app.optimization.optimizer import run_gepa

_AGENTS = ("document_intelligence", "data_steward", "clinical_summary")


async def load_trainset_from_db(min_runs: int = 50) -> dict[str, list[dspy.Example]]:
    trainset: dict[str, list[dspy.Example]] = {name: [] for name in _AGENTS}
    async with SessionLocal() as session:
        for agent_name in _AGENTS:
            rows = (
                await session.execute(
                    select(AgentRunLog)
                    .where(AgentRunLog.agent_name == agent_name, AgentRunLog.success.is_(True))
                    .order_by(AgentRunLog.created_at.desc())
                    .limit(min_runs)
                )
            ).scalars().all()
            trainset[agent_name] = [_example_for_run(agent_name, row) for row in rows]
    return trainset


def _example_for_run(agent_name: str, row: AgentRunLog) -> dspy.Example:
    inputs = row.inputs_snapshot or {}
    outputs = row.outputs_snapshot or {}
    if agent_name == "document_intelligence":
        return dspy.Example(
            ocr_text=inputs.get("ocr_text", ""),
            clinical_findings=outputs.get("clinical_findings", []),
        ).with_inputs("ocr_text")
    if agent_name == "data_steward":
        return dspy.Example(
            document_understanding=inputs.get("document_understanding", {}),
            current_patient_record=inputs.get("current_patient_record", {}),
            flags_raised_fields=[
                item.get("field") for item in outputs.get("flags_raised", []) if item.get("field")
            ],
            demographic_fields_updated=[],
        ).with_inputs("document_understanding", "current_patient_record")
    return dspy.Example(
        patient_context=inputs.get("patient_context", {}),
        recent_changes=inputs.get("recent_changes", {}),
        trends=inputs.get("trends", {}),
        resolved_flags=inputs.get("resolved_flags", []),
        flags_raised=inputs.get("resolved_flags", []),
        full_narrative=outputs.get("full_narrative", ""),
    ).with_inputs("patient_context", "recent_changes", "trends", "resolved_flags")


async def main() -> None:
    trainset = await load_trainset_from_db(min_runs=50)
    run_gepa(
        DocumentIntelligenceAgent(),
        document_intelligence_metric,
        trainset["document_intelligence"],
        "app/optimization/compiled/document_intelligence.json",
    )
    run_gepa(
        PatientDataStewardAgent(),
        stewardship_metric,
        trainset["data_steward"],
        "app/optimization/compiled/data_steward.json",
    )
    run_gepa(
        ClinicalSummaryAgent(),
        summary_metric,
        trainset["clinical_summary"],
        "app/optimization/compiled/clinical_summary.json",
    )


if __name__ == "__main__":
    asyncio.run(main())
