"""Application configuration via Pydantic Settings.

All settings are read from environment variables or a `.env` file in the working
directory. See `.env.example` for a full template.

Usage:
    from app.config import get_settings
    settings = get_settings()   # cached singleton

Key groups:
    - Database: DATABASE_URL (Postgres — asyncpg driver required)
    - Auth: JWT_SECRET, JWT_EXPIRE_MINUTES
    - AI: AI_PROVIDER ("openrouter" | "ollama"), per-role model IDs
    - OCR: OCR_ENGINE, OCR_MAX_PAGES
    - Queue: QUEUE_MAX_CONCURRENCY (bounded asyncio worker pool)
    - Storage: DOCUMENT_STORE ("local"), LOCAL_STORE_PATH
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application settings, sourced from environment variables or .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: str = "dev"
    app_debug: bool = True

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://medx:medx@localhost:5433/medx"

    # ── Auth / JWT ────────────────────────────────────────────────────────────
    jwt_secret: str = Field(default="dev-secret-change-me")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # ── Document storage ─────────────────────────────────────────────────────
    document_store: str = "local"       # "local" | "s3"
    local_store_path: str = "./uploads"

    # ── AI provider ──────────────────────────────────────────────────────────
    # "openrouter" uses cloud models; "ollama" routes all roles to ollama_model.
    ai_provider: str = "openrouter"

    # OpenRouter (OpenAI-compatible API)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_title: str = "MedX"
    openrouter_timeout_s: float = 90.0

    # Ollama (OpenAI-compatible local API)
    ollama_base_url: str = "http://192.168.2.17:11434/v1"
    ollama_model: str = "gemma4:e4b"
    ollama_timeout_s: float = 120.0

    # Per-role model IDs — used only when ai_provider="openrouter".
    # VISION_OCR always uses OpenRouter even when ai_provider="ollama" unless
    # the Ollama model is multimodal (e.g. gemma4).
    ai_model_classify: str = "google/gemini-2.0-flash-exp:free"
    ai_model_extract: str = "deepseek/deepseek-chat-v3:free"
    ai_model_extract_alt: str = "meta-llama/llama-3.3-70b-instruct:free"
    ai_model_vision_ocr: str = "qwen/qwen2.5-vl-72b-instruct:free"
    ai_model_summarize: str = "google/gemini-2.0-flash-exp:free"
    ai_model_chat: str = "mistralai/mistral-small-3.1-24b-instruct:free"
    ai_model_synthetic_gen: str = "deepseek/deepseek-chat-v3:free"

    # ── OCR ───────────────────────────────────────────────────────────────────
    ocr_engine: str = "openrouter_vision"   # "pypdf" | "openrouter_vision" | "marker"
    ocr_max_pages: int = 30                 # PDFs with more pages are rejected at upload

    # ── Background queue ─────────────────────────────────────────────────────
    queue_backend: str = "inprocess"        # "inprocess" | "arq" (Phase 5)
    queue_max_concurrency: int = 2          # Parallel AI pipeline workers


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings singleton.

    Uses lru_cache so settings are parsed from the environment exactly once per
    process. Call `get_settings.cache_clear()` in tests to reload from a patched env.
    """
    return Settings()
