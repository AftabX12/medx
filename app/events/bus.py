"""In-process SSE event bus keyed by document_id.

Subscribers receive pipeline step events as they're emitted by router.py.
The bus is intentionally simple: no persistence, no replay. Events are
fire-and-forget; missed events are fine because the viewer re-reads DB state
on connection.

Usage:
    # Emit (from pipeline router):
    await get_event_bus().emit(document_id, {"step": "classify", "status": "ok"})

    # Subscribe (from SSE endpoint):
    async for event in get_event_bus().subscribe(document_id):
        yield event  # dict → serialized by caller
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import AsyncIterator


class EventBus:
    def __init__(self) -> None:
        # document_id → set of subscriber queues
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue]] = defaultdict(set)

    async def emit(self, document_id: uuid.UUID, payload: dict) -> None:
        queues = self._subscribers.get(document_id, set())
        for q in list(queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # slow subscriber; drop rather than block pipeline

    async def subscribe(
        self,
        document_id: uuid.UUID,
        *,
        maxsize: int = 64,
        timeout: float = 120.0,
    ) -> AsyncIterator[dict]:
        """Yield events for document_id until a 'done' or 'failed' event or timeout."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers[document_id].add(q)
        try:
            deadline = asyncio.get_event_loop().time() + timeout
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=min(remaining, 5.0))
                except asyncio.TimeoutError:
                    # Send a keepalive comment so the connection stays alive
                    yield {"type": "keepalive"}
                    continue
                yield event
                # Terminal events — pipeline finished
                if event.get("type") in ("done", "failed"):
                    break
        finally:
            self._subscribers[document_id].discard(q)
            if not self._subscribers[document_id]:
                self._subscribers.pop(document_id, None)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
