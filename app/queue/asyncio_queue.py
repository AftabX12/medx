"""In-process asyncio task queue.

FastAPI BackgroundTasks has no concurrency cap and crashes the request loop if
the handler raises — both fatal for rate-limited AI jobs. This queue runs a
bounded worker pool attached to the app lifespan. arq/Redis replaces it in
Phase 5 (multi-process / persistent deployments).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.logging import get_logger

log = get_logger(__name__)

JobHandler = Callable[..., Awaitable[None]]


@dataclass
class Job:
    name: str
    kwargs: dict[str, Any]


class InProcessQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Job] | None = None
        self._workers: list[asyncio.Task] = []
        self._handlers: dict[str, JobHandler] = {}
        self._running = False

    def register(self, name: str, handler: JobHandler) -> None:
        self._handlers[name] = handler

    async def start(self, concurrency: int, *, recover_pending: bool = True) -> None:
        if self._running:
            return
        self._queue = asyncio.Queue()
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i)) for i in range(concurrency)
        ]
        log.info("queue_started", concurrency=concurrency)
        if recover_pending:
            await self._recover_pending()

    async def stop(self, *, drain: bool = True) -> None:
        if not self._running:
            return
        if drain and self._queue is not None:
            await self._queue.join()
        self._running = False
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._workers = []
        self._queue = None
        log.info("queue_stopped")

    async def enqueue(self, job_name: str, **kwargs: Any) -> None:
        if self._queue is None:
            raise RuntimeError("queue not started")
        if job_name not in self._handlers:
            raise ValueError(f"unknown job: {job_name}")
        await self._queue.put(Job(name=job_name, kwargs=kwargs))

    async def join(self) -> None:
        """Block until all queued jobs are done. Test helper."""
        if self._queue is not None:
            await self._queue.join()

    async def _worker(self, idx: int) -> None:
        assert self._queue is not None
        while self._running:
            try:
                job = await self._queue.get()
            except asyncio.CancelledError:
                return
            try:
                handler = self._handlers[job.name]
                await handler(**job.kwargs)
            except Exception as exc:  # noqa: BLE001
                log.warning("job_failed", job=job.name, worker=idx, error=str(exc))
            finally:
                self._queue.task_done()

    async def _recover_pending(self) -> None:
        """Re-enqueue up to 100 documents stuck in ocr_status='pending'."""
        try:
            from sqlalchemy import select

            from app.db.models import Document
            from app.db.session import SessionLocal

            async with SessionLocal() as session:
                rows = (
                    await session.execute(
                        select(Document.id, Document.tenant_id)
                        .where(Document.ocr_status == "pending")
                        .limit(100)
                    )
                ).all()
            for doc_id, tenant_id in rows:
                await self.enqueue(
                    "ocr_process", document_id=doc_id, tenant_id=tenant_id
                )
            if len(rows) == 100:
                log.warning(
                    "queue_recover_truncated",
                    note="more than 100 pending docs; run scripts/reprocess_pending.py",
                )
            elif rows:
                log.info("queue_recovered_pending", count=len(rows))
        except Exception as exc:  # noqa: BLE001
            log.info("queue_recover_skipped", error=str(exc))


_queue_singleton: InProcessQueue | None = None


def get_queue() -> InProcessQueue:
    global _queue_singleton
    if _queue_singleton is None:
        _queue_singleton = InProcessQueue()
        from app.queue import jobs

        jobs.register_all(_queue_singleton)
    return _queue_singleton


def set_queue(q: InProcessQueue | None) -> None:
    """Test hook: override or clear the singleton."""
    global _queue_singleton
    _queue_singleton = q
