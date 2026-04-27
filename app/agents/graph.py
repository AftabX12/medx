"""LangGraph pipeline graph.

document_intelligence — DSPy ChainOfThought agent (Phase 2)
data_steward          — DSPy ReAct agent (Phase 3)
clinical_summary      — DSPy ChainOfThought agent (Phase 5)

Graph structure:
    document_intelligence → data_steward → [flag_review] → clinical_summary → END
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from time import perf_counter
from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph

from app.agents.run_logging import log_agent_run
from app.agents.state import PipelineEvent, PipelineState
from app.db.session import SessionLocal
from app.events import get_event_bus
from app.logging import get_logger

if TYPE_CHECKING:
    from app.agents.clinical_summary.agent import ClinicalSummaryAgent
    from app.agents.data_steward.agent import PatientDataStewardAgent
    from app.agents.document_intelligence.agent import DocumentIntelligenceAgent

log = get_logger(__name__)

# Singleton compiled graph
_compiled_graph = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _set_step(session, doc, step: str, status: str, detail: str = "") -> None:
    """Update pipeline_status on the Document and push an SSE event."""
    ps = dict(doc.pipeline_status or {})
    ps[step] = {"status": status, "ts": _now(), "detail": detail}
    doc.pipeline_status = ps
    await session.flush()
    await get_event_bus().emit(
        doc.id, {"type": "step", "step": step, "status": status, "detail": detail}
    )


# ---------------------------------------------------------------------------
# Agent singletons (instantiated once, reused across all graph invocations)
# ---------------------------------------------------------------------------

_dia: DocumentIntelligenceAgent | None = None
_steward: PatientDataStewardAgent | None = None
_summary_agent: ClinicalSummaryAgent | None = None


def _get_dia() -> DocumentIntelligenceAgent:
    global _dia
    if _dia is None:
        from app.agents.document_intelligence.agent import DocumentIntelligenceAgent
        from app.agents.registry import get_agent
        _dia = get_agent("document_intelligence") or DocumentIntelligenceAgent()
    return _dia


def _get_steward() -> PatientDataStewardAgent:
    global _steward
    if _steward is None:
        from app.agents.data_steward.agent import PatientDataStewardAgent
        from app.agents.registry import get_agent
        _steward = get_agent("data_steward") or PatientDataStewardAgent()
    return _steward


def _get_summary_agent() -> ClinicalSummaryAgent:
    global _summary_agent
    if _summary_agent is None:
        from app.agents.clinical_summary.agent import ClinicalSummaryAgent
        from app.agents.registry import get_agent
        _summary_agent = get_agent("clinical_summary") or ClinicalSummaryAgent()
    return _summary_agent


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def document_intelligence_node(state: PipelineState) -> dict:
    """DSPy ChainOfThought agent: open-ended document understanding."""
    from app.db.models import Document

    document_id = uuid.UUID(state["document_id"])

    if not state["ocr_text"].strip():
        async with SessionLocal() as session:
            doc = await session.get(Document, document_id)
            if doc:
                await _set_step(session, doc, "document_intelligence", "skipped", "no OCR text")
                await session.commit()
        return {
            "events": [PipelineEvent(step="document_intelligence", status="skipped", detail="no OCR text")]
        }

    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return {
                "events": [PipelineEvent(step="document_intelligence", status="failed", detail="document not found")]
            }
        await _set_step(session, doc, "document_intelligence", "running")
        await session.commit()

    start = perf_counter()
    try:
        understanding = _get_dia()(ocr_text=state["ocr_text"])
    except Exception as exc:
        async with SessionLocal() as session:
            doc = await session.get(Document, document_id)
            if doc:
                await _set_step(session, doc, "document_intelligence", "failed", str(exc))
                await session.commit()
        await log_agent_run(
            tenant_id=state["tenant_id"],
            document_id=state["document_id"],
            agent_name="document_intelligence",
            inputs_snapshot={"ocr_text": state["ocr_text"][:10000]},
            outputs_snapshot={"error": str(exc)},
            tool_calls=[],
            duration_ms=int((perf_counter() - start) * 1000),
            success=False,
        )
        return {
            "error": str(exc),
            "events": [PipelineEvent(step="document_intelligence", status="failed", detail=str(exc))],
        }

    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc:
            doc.doc_type = understanding["document_nature"]
            await _set_step(session, doc, "document_intelligence", "ok", understanding["document_nature"])
            await session.commit()

    await log_agent_run(
        tenant_id=state["tenant_id"],
        document_id=state["document_id"],
        agent_name="document_intelligence",
        inputs_snapshot={"ocr_text": state["ocr_text"][:10000]},
        outputs_snapshot=understanding,
        tool_calls=[],
        duration_ms=int((perf_counter() - start) * 1000),
        success=True,
    )
    return {
        "document_understanding": understanding,
        "events": [PipelineEvent(
            step="document_intelligence",
            status="ok",
            detail=understanding["document_nature"],
        )],
    }


async def data_steward_node(state: PipelineState) -> dict:
    """Apply stewardship rules to the document-understanding output."""
    from app.agents.data_steward.tools import (
        load_pending_flags,
        reset_tool_context,
        set_tool_context,
    )
    from app.db.models import Document

    document_id = uuid.UUID(state["document_id"])
    tenant_id = uuid.UUID(state["tenant_id"])
    understanding = state.get("document_understanding")

    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return {
                "events": [PipelineEvent(step="data_steward", status="failed", detail="document not found")]
            }
        if not understanding:
            await _set_step(session, doc, "profile", "skipped", "no document understanding")
            await session.commit()
            return {
                "human_review_pending": False,
                "events": [PipelineEvent(step="data_steward", status="skipped", detail="no document understanding")],
            }

        await _set_step(session, doc, "profile", "running")
        await session.commit()

    start = perf_counter()
    try:
        result = await _get_steward().forward(
            document_understanding=understanding,
            patient_id=state["patient_id"],
            tenant_id=state["tenant_id"],
            document_id=state["document_id"],
        )
        token = set_tool_context(tenant_id=tenant_id)
        try:
            pending_flags = await load_pending_flags(state["document_id"])
        finally:
            reset_tool_context(token)
        detail = (
            f"{len(result['actions_taken'])} action(s); {len(pending_flags)} flag(s) raised"
        )
        async with SessionLocal() as session:
            doc = await session.get(Document, document_id)
            if doc:
                await _set_step(session, doc, "profile", "ok", detail)
                await session.commit()
    except Exception as exc:
        async with SessionLocal() as session:
            doc = await session.get(Document, document_id)
            if doc:
                await _set_step(session, doc, "profile", "failed", str(exc))
                await session.commit()
        log.warning("data_steward_failed", error=str(exc))
        await log_agent_run(
            tenant_id=state["tenant_id"],
            document_id=state["document_id"],
            agent_name="data_steward",
            inputs_snapshot={"document_understanding": understanding, "patient_id": state["patient_id"]},
            outputs_snapshot={"error": str(exc)},
            tool_calls=[],
            duration_ms=int((perf_counter() - start) * 1000),
            success=False,
        )
        return {
            "error": str(exc),
            "events": [PipelineEvent(step="data_steward", status="failed", detail=str(exc))],
        }

    await log_agent_run(
        tenant_id=state["tenant_id"],
        document_id=state["document_id"],
        agent_name="data_steward",
        inputs_snapshot={"document_understanding": understanding, "patient_id": state["patient_id"]},
        outputs_snapshot=result,
        tool_calls=result.get("actions_taken", []) + result.get("flags_raised", []),
        duration_ms=int((perf_counter() - start) * 1000),
        success=True,
    )
    return {
        "stewardship_result": result,
        "pending_flags": pending_flags,
        "human_review_pending": len(pending_flags) > 0,
        "events": [PipelineEvent(step="data_steward", status="ok", detail=detail)],
    }


async def flag_review_node(state: PipelineState) -> dict:
    """Pause the graph while a clinician resolves reconciliation flags."""
    from langgraph.types import interrupt

    from app.db.models import Document

    document_id = uuid.UUID(state["document_id"])
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc:
            await _set_step(session, doc, "flag_review", "pending", "awaiting clinician review")
            await session.commit()

    human_decisions = interrupt({
        "type": "flag_review",
        "flags": state.get("pending_flags", []),
        "patient_id": state["patient_id"],
        "document_id": state["document_id"],
    })

    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc:
            await _set_step(session, doc, "flag_review", "ok", f"{len(human_decisions)} decision(s)")
            await session.commit()

    return {
        "human_decisions": human_decisions,
        "human_review_pending": False,
    }


async def apply_demographic_update(session, decision: dict) -> None:
    """Apply a clinician-approved patient-profile flag decision."""
    from app.db.models import Patient, ReconcileFlag

    if decision.get("choice") != "use_new":
        return

    flag_id = decision.get("flag_id")
    if not flag_id:
        return

    flag = await session.get(ReconcileFlag, uuid.UUID(str(flag_id)))
    if not flag or flag.resource_type != "patient_profile":
        return

    field = flag.details.get("field")
    doc_val = flag.details.get("document_value")
    if not field or doc_val in (None, ""):
        return

    patient = await session.get(Patient, flag.patient_id)
    if not patient or not hasattr(patient, field):
        return

    if field == "date_of_birth":
        try:
            doc_val = date.fromisoformat(str(doc_val))
        except ValueError:
            return
    setattr(patient, field, doc_val)


async def apply_decisions_node(state: PipelineState) -> dict:
    """Apply human decisions before clinical summary generation."""
    from app.db.models import Document, ReconcileFlag

    decisions = state.get("human_decisions", [])
    async with SessionLocal() as session:
        for decision in decisions:
            await apply_demographic_update(session, decision)
            flag_id = decision.get("flag_id")
            if flag_id:
                flag = await session.get(ReconcileFlag, uuid.UUID(str(flag_id)))
                if flag:
                    flag.resolution_choice = decision.get("choice")
                    flag.resolution_note = decision.get("note")
                    flag.resolved = True
                    flag.resolved_at = datetime.now(UTC)
                    flag.resolved_by = "doctor"
        doc = await session.get(Document, uuid.UUID(state["document_id"]))
        if doc:
            await _set_step(
                session,
                doc,
                "apply_decisions",
                "ok",
                f"{len(decisions)} decision(s) applied",
            )
        await session.commit()
    return {
        "events": [
            PipelineEvent(
                step="apply_decisions",
                status="ok",
                detail=f"{len(decisions)} decision(s) applied",
            )
        ]
    }


async def clinical_summary_node(state: PipelineState) -> dict:
    """Write and persist a doctor-ready clinical summary."""
    from app.db.models import Document, Patient

    document_id = uuid.UUID(state["document_id"])
    tenant_id = uuid.UUID(state["tenant_id"])

    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return {
                "events": [PipelineEvent(step="clinical_summary", status="failed", detail="document not found")]
            }

        await _set_step(session, doc, "summarize", "running")
        await session.commit()

    start = perf_counter()
    inputs_snapshot = {
        "patient_id": state["patient_id"],
        "document_id": state["document_id"],
        "trends": state.get("stewardship_result", {}).get("trends", {}),
        "resolved_flags": [d for d in state.get("human_decisions", [])],
    }
    try:
        summary = await _get_summary_agent().forward(
            patient_id=state["patient_id"],
            document_id=state["document_id"],
            tenant_id=state["tenant_id"],
            trends=state.get("stewardship_result", {}).get("trends", {}),
            resolved_flags=[d for d in state.get("human_decisions", [])],
        )
        async with SessionLocal() as session:
            patient = await session.get(Patient, uuid.UUID(state["patient_id"]))
            if patient and summary:
                patient.ai_summary = summary
            doc = await session.get(Document, document_id)
            if doc and doc.tenant_id == tenant_id:
                await _set_step(session, doc, "summarize", "ok")
            await session.commit()
    except Exception as exc:
        async with SessionLocal() as session:
            doc = await session.get(Document, document_id)
            if doc:
                await _set_step(session, doc, "summarize", "failed", str(exc))
                await session.commit()
        log.warning("clinical_summary_failed", error=str(exc))
        await log_agent_run(
            tenant_id=state["tenant_id"],
            document_id=state["document_id"],
            agent_name="clinical_summary",
            inputs_snapshot=inputs_snapshot,
            outputs_snapshot={"error": str(exc)},
            tool_calls=[],
            duration_ms=int((perf_counter() - start) * 1000),
            success=False,
        )
        return {
            "events": [PipelineEvent(step="clinical_summary", status="failed", detail=str(exc))]
        }

    await get_event_bus().emit(uuid.UUID(state["document_id"]), {"type": "done"})
    await log_agent_run(
        tenant_id=state["tenant_id"],
        document_id=state["document_id"],
        agent_name="clinical_summary",
        inputs_snapshot=inputs_snapshot,
        outputs_snapshot={"full_narrative": summary},
        tool_calls=[],
        duration_ms=int((perf_counter() - start) * 1000),
        success=True,
    )
    return {
        "clinical_summary": summary,
        "events": [PipelineEvent(step="clinical_summary", status="ok")],
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_after_steward(state: PipelineState) -> str:
    if state.get("pending_flags"):
        return "flag_review"
    return "clinical_summary"


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_graph(checkpointer):
    graph = StateGraph(PipelineState)
    graph.add_node("document_intelligence", document_intelligence_node)
    graph.add_node("data_steward", data_steward_node)
    graph.add_node("flag_review", flag_review_node)
    graph.add_node("apply_decisions", apply_decisions_node)
    graph.add_node("clinical_summary", clinical_summary_node)

    graph.set_entry_point("document_intelligence")
    graph.add_edge("document_intelligence", "data_steward")
    graph.add_conditional_edges(
        "data_steward",
        route_after_steward,
        {"flag_review": "flag_review", "clinical_summary": "clinical_summary"},
    )
    graph.add_edge("flag_review", "apply_decisions")
    graph.add_edge("apply_decisions", "clinical_summary")
    graph.add_edge("clinical_summary", END)

    return graph.compile(checkpointer=checkpointer)


def get_compiled_graph():
    global _compiled_graph
    if _compiled_graph is None:
        from app.agents.checkpointer import get_checkpointer
        _compiled_graph = build_graph(get_checkpointer())
    return _compiled_graph
