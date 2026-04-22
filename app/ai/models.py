from enum import StrEnum

from app.config import Settings


class ModelRole(StrEnum):
    CLASSIFY = "classify"
    EXTRACT = "extract"
    EXTRACT_ALT = "extract_alt"
    VISION_OCR = "vision_ocr"
    SUMMARIZE = "summarize"
    CHAT = "chat"
    SYNTHETIC_GEN = "synthetic_gen"


def resolve_model(role: ModelRole, settings: Settings) -> str:
    if settings.ai_provider == "ollama":
        return settings.ollama_model
    if not settings.openrouter_model:
        raise ValueError("OPENROUTER_MODEL is not configured")
    return settings.openrouter_model
