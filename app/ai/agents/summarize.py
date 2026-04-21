"""Generate a clinical narrative summary of a patient given their extracted data."""

from __future__ import annotations

from app.ai.client import OpenRouterClient, get_ai_client
from app.ai.models import ModelRole

_SYSTEM = (
    "You are a clinical summarization assistant. Given structured patient data — "
    "demographics, current medications, active problems, and recent observations — "
    "write a concise 2-4 sentence clinical narrative. Focus on: current issues, "
    "active medications, and key abnormal lab values. Be factual and brief. "
    "Do not invent information not present in the data."
)


async def summarize_patient(context: dict, *, client: OpenRouterClient | None = None) -> str:
    c = client or get_ai_client()
    import json
    user_text = json.dumps(context, default=str, indent=2)[:6000]
    resp = await c.complete_text(
        role=ModelRole.SUMMARIZE,
        system=_SYSTEM,
        user=user_text,
        temperature=0.2,
        max_tokens=512,
    )
    return (resp.content or "").strip()
