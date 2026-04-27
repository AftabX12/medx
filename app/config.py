"""Application configuration via Pydantic Settings.

All settings are read from environment variables or a `.env` file in the working
directory. See `.env.example` for a full template.

Usage:
    from app.config import get_settings
    settings = get_settings()   # cached singleton

Key groups:
    - Database: DATABASE_URL
    - Auth: JWT_SECRET, JWT_EXPIRE_MINUTES
    - AI: AI_PROVIDER ("openrouter" | "ollama"), OPENROUTER_MODEL / OLLAMA_MODEL
    - OCR: OCR_ENGINE ("pypdf" | "openrouter" | "ollama")
    - Queue: QUEUE_MAX_CONCURRENCY
    - Storage: DOCUMENT_STORE, LOCAL_STORE_PATH
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application settings, sourced from environment variables or .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: str = "dev"
    app_debug: bool = True

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str

    # ── Auth / JWT ────────────────────────────────────────────────────────────
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # ── Document storage ─────────────────────────────────────────────────────
    document_store: str = "local"       # "local" | "s3"
    local_store_path: str = "./uploads"

    # ── AI provider ──────────────────────────────────────────────────────────
    ai_provider: str = "openrouter"     # "openrouter" | "ollama"

    # OpenRouter — only needed when AI_PROVIDER=openrouter or OCR_ENGINE=openrouter
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_title: str = "MedX"
    openrouter_timeout_s: float = 90.0
    openrouter_model: str = ""

    # Ollama — only needed when AI_PROVIDER=ollama or OCR_ENGINE=ollama
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = ""
    ollama_vision_model: str = ""      # vision model for OCR; falls back to ollama_model if empty
    ollama_timeout_s: float = 120.0

    @model_validator(mode="after")
    def _validate_provider_settings(self) -> "Settings":
        needs_openrouter = self.ai_provider == "openrouter" or self.ocr_engine == "openrouter"
        needs_ollama = self.ai_provider == "ollama" or self.ocr_engine == "ollama"
        if needs_openrouter:
            if not self.openrouter_api_key:
                raise ValueError("OPENROUTER_API_KEY is required when AI_PROVIDER=openrouter or OCR_ENGINE=openrouter")
            if not self.openrouter_model:
                raise ValueError("OPENROUTER_MODEL is required when AI_PROVIDER=openrouter or OCR_ENGINE=openrouter")
        if needs_ollama and not self.ollama_model:
            raise ValueError("OLLAMA_MODEL is required when AI_PROVIDER=ollama or OCR_ENGINE=ollama")
        return self

    # ── OCR ───────────────────────────────────────────────────────────────────
    # "pypdf"       — text-layer extraction (default, no AI)
    # "openrouter"  — vision OCR via OpenRouter (uses openrouter_model)
    # "ollama"      — vision OCR via Ollama (uses ollama_model / ollama_vision_model)
    ocr_engine: str = "pypdf"
    ocr_max_pages: int = 200

    # ── Anthropic / DSPy ─────────────────────────────────────────────────────
    anthropic_api_key: str = ""             # enables Claude as primary LLM for agents
    dspy_cache_dir: str = ".dspy_cache"     # local cache for DSPy LM calls

    # ── Background queue ─────────────────────────────────────────────────────
    queue_backend: str = "inprocess"        # "inprocess" | "arq" (Phase 5)
    queue_max_concurrency: int = 2

    # ── Seed admin (created on first startup if absent) ──────────────────────
    seed_tenant_name: str
    seed_admin_email: str
    seed_admin_password: str
    seed_admin_name: str


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings singleton.

    Uses lru_cache so settings are parsed from the environment exactly once per
    process. Call `get_settings.cache_clear()` in tests to reload from a patched env.
    """
    return Settings()
