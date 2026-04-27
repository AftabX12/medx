"""LangGraph checkpointer setup."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)

_checkpointer: Any | None = None
_checkpointer_cm: Any | None = None


def _postgres_checkpoint_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def setup_checkpointer():
    """Create the singleton graph checkpointer.

    Phase 4 uses LangGraph's PostgreSQL checkpointer for durable interrupt/resume.
    SQLite/dev environments fall back to MemorySaver because the PostgreSQL saver
    only works with PostgreSQL connections.
    """
    global _checkpointer, _checkpointer_cm
    if _checkpointer is not None:
        return _checkpointer

    settings = get_settings()
    if settings.database_url.startswith("postgresql"):
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ModuleNotFoundError:
            log.warning(
                "postgres_checkpointer_unavailable",
                detail="Install langgraph-checkpoint-postgres to enable durable graph resume.",
            )
        else:
            _checkpointer_cm = AsyncPostgresSaver.from_conn_string(
                _postgres_checkpoint_url(settings.database_url)
            )
            _checkpointer = await _checkpointer_cm.__aenter__()
            await _checkpointer.setup()
            return _checkpointer

    _checkpointer = MemorySaver()
    return _checkpointer


async def close_checkpointer() -> None:
    global _checkpointer, _checkpointer_cm
    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)
    _checkpointer = None
    _checkpointer_cm = None


def get_checkpointer():
    if _checkpointer is None:
        raise RuntimeError("Checkpointer not initialised — call setup_checkpointer() first")
    return _checkpointer
