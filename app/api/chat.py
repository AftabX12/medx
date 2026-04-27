"""Chat endpoint: doctor asks questions about their patients and EHR data."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.chat.agent import ChatAgent
from app.deps import CurrentUser, SessionDep

router = APIRouter(tags=["chat"])

_chat_agent: ChatAgent | None = None


class ChatRequest(BaseModel):
    question: str
    patient_id: str | None = None


class ChatResponse(BaseModel):
    answer: str


def _get_chat_agent() -> ChatAgent:
    global _chat_agent
    if _chat_agent is None:
        from app.agents.registry import get_agent
        _chat_agent = get_agent("chat") or ChatAgent()
    return _chat_agent


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, session: SessionDep, user: CurrentUser) -> ChatResponse:
    """Answer a clinical question using DSPy ReAct tools over tenant-scoped EHR data."""
    del session
    try:
        answer = await _get_chat_agent().forward(
            question=body.question,
            patient_id=body.patient_id or "clinic",
            tenant_id=str(user.tenant_id),
        )
    except Exception:
        answer = "An error occurred while generating a response. Please try again."
    return ChatResponse(answer=answer)
