from __future__ import annotations

import json
import uuid
from typing import Any

from app.logging import get_logger

log = get_logger(__name__)

_MAX_SNAPSHOT_CHARS = 12000


def truncate_snapshot(value: Any) -> Any:
    try:
        text = json.dumps(value, default=str)
    except TypeError:
        return str(value)[:_MAX_SNAPSHOT_CHARS]
    if len(text) <= _MAX_SNAPSHOT_CHARS:
        return value
    return {"truncated": True, "json": text[:_MAX_SNAPSHOT_CHARS]}


async def log_agent_run(
    *,
    tenant_id: str | uuid.UUID,
    agent_name: str,
    inputs_snapshot: dict,
    outputs_snapshot: dict,
    duration_ms: int,
    success: bool,
    document_id: str | uuid.UUID | None = None,
    tool_calls: list | None = None,
) -> None:
    try:
        from app.db.models import AgentRunLog
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            session.add(
                AgentRunLog(
                    tenant_id=_as_uuid(tenant_id),
                    document_id=_as_uuid(document_id) if document_id else None,
                    agent_name=agent_name,
                    inputs_snapshot=truncate_snapshot(inputs_snapshot),
                    outputs_snapshot=truncate_snapshot(outputs_snapshot),
                    tool_calls=tool_calls or [],
                    duration_ms=duration_ms,
                    success=success,
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("agent_run_log_failed", agent_name=agent_name, error=str(exc))


def _as_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
