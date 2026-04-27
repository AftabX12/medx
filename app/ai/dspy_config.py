"""DSPy LM configuration.

Wires DSPy to the same provider configured via AI_PROVIDER — Ollama or OpenRouter.
Anthropic is an optional override if ANTHROPIC_API_KEY is set.

Usage:
    from app.ai.dspy_config import configure_dspy
    configure_dspy()   # called once in lifespan
"""

from __future__ import annotations

import dspy

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)


def configure_dspy() -> None:
    """Wire DSPy to the LM specified in Settings.

    Priority:
    1. Anthropic Claude (only if ANTHROPIC_API_KEY explicitly set)
    2. Ollama (when AI_PROVIDER=ollama)
    3. OpenRouter (when AI_PROVIDER=openrouter)
    """
    s = get_settings()

    if s.anthropic_api_key:
        lm = dspy.LM(
            model="anthropic/claude-sonnet-4-6",
            api_key=s.anthropic_api_key,
            cache_dir=s.dspy_cache_dir,
        )
        log.info("dspy_lm_configured", provider="anthropic", model="claude-sonnet-4-6")

    elif s.ai_provider == "ollama":
        lm = dspy.LM(
            model=f"ollama_chat/{s.ollama_model}",
            api_base=s.ollama_base_url,
            cache_dir=s.dspy_cache_dir,
        )
        log.info("dspy_lm_configured", provider="ollama", model=s.ollama_model)

    else:
        # openrouter — DSPy speaks OpenAI-compatible, so pass api_base
        lm = dspy.LM(
            model=f"openai/{s.openrouter_model}",
            api_key=s.openrouter_api_key,
            api_base=s.openrouter_base_url,
            cache_dir=s.dspy_cache_dir,
        )
        log.info("dspy_lm_configured", provider="openrouter", model=s.openrouter_model)

    dspy.configure(lm=lm)
