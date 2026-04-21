"""Medical chatbot: answer questions about the EHR data for the current tenant."""

from __future__ import annotations

from app.ai.client import OpenRouterClient, get_ai_client
from app.ai.models import ModelRole

_SYSTEM = """You are MedX Assistant, a clinical AI helper embedded in the MedX EHR system.
You have access to the following patient data for this clinic (provided below as JSON context).
Answer the doctor's question accurately and concisely, citing patient names or MRNs where relevant.
Never invent data that is not in the context. If the answer is not in the context say so clearly.
Keep responses brief — 2-4 sentences unless the question requires a list."""


async def chat_answer(question: str, context: dict, *, client: OpenRouterClient | None = None) -> str:
    import json
    c = client or get_ai_client()
    # Build a compact summary header so the model always knows totals,
    # then include the full patient list (capped to avoid token limits).
    header = (
        f"Clinic summary: {context.get('total_patients', 0)} patients, "
        f"{context.get('total_documents', 0)} documents uploaded "
        f"(status breakdown: {context.get('document_status_breakdown', {})})."
    )
    patients_json = json.dumps(context.get("patients", []), default=str, indent=2)
    # Cap at 24 000 chars (~6k tokens) — enough for ~20 patients with full clinical data
    ctx_text = header + "\n\nPatients:\n" + patients_json[:24000]
    resp = await c.complete_text(
        role=ModelRole.CHAT,
        system=_SYSTEM + f"\n\n<context>\n{ctx_text}\n</context>",
        user=question,
        temperature=0.1,
        max_tokens=1024,
        max_attempts=2,
    )
    return (resp.content or "I could not generate a response.").strip()
