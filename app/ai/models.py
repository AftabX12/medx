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


_ROLE_TO_SETTING = {
    ModelRole.CLASSIFY: "ai_model_classify",
    ModelRole.EXTRACT: "ai_model_extract",
    ModelRole.EXTRACT_ALT: "ai_model_extract_alt",
    ModelRole.VISION_OCR: "ai_model_vision_ocr",
    ModelRole.SUMMARIZE: "ai_model_summarize",
    ModelRole.CHAT: "ai_model_chat",
    ModelRole.SYNTHETIC_GEN: "ai_model_synthetic_gen",
}


def resolve_model(role: ModelRole, settings: Settings) -> str:
    # Ollama provider: all roles (including vision OCR) use the local model.
    # gemma4 is multimodal so vision OCR works natively on Ollama.
    if settings.ai_provider == "ollama":
        return settings.ollama_model
    attr = _ROLE_TO_SETTING[role]
    name = getattr(settings, attr, "")
    if not name:
        raise ValueError(f"No model configured for role {role.value} (setting {attr})")
    return name
