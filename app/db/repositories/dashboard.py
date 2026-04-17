"""Tenant-scoped aggregations for the dashboard landing page."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, Patient


_NEEDS_ATTENTION = ("failed", "no_text", "unsupported")
_KNOWN_STATUSES = ("pending", "ok", "failed", "no_text", "unsupported")


class DashboardRepository:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def patient_count(self) -> int:
        stmt = select(func.count(Patient.id)).where(Patient.tenant_id == self.tenant_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def document_counts_by_status(self) -> dict[str, int]:
        stmt = (
            select(Document.ocr_status, func.count(Document.id))
            .where(Document.tenant_id == self.tenant_id)
            .group_by(Document.ocr_status)
        )
        result = await self.session.execute(stmt)
        counts = {s: 0 for s in _KNOWN_STATUSES}
        for status, n in result.all():
            counts[status] = int(n)
        return counts

    async def recent_uploads(self, limit: int = 10) -> list[tuple[Document, Patient]]:
        stmt = (
            select(Document, Patient)
            .join(Patient, Patient.id == Document.patient_id)
            .where(Document.tenant_id == self.tenant_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [(d, p) for d, p in result.all()]

    async def docs_needing_attention(self, limit: int = 10) -> list[tuple[Document, Patient]]:
        stmt = (
            select(Document, Patient)
            .join(Patient, Patient.id == Document.patient_id)
            .where(
                Document.tenant_id == self.tenant_id,
                Document.ocr_status.in_(_NEEDS_ATTENTION),
            )
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [(d, p) for d, p in result.all()]

    def storage_stats(self, root: str | Path) -> tuple[int, int]:
        """Return (total_bytes, file_count) for this tenant's directory.

        Safe because LocalDiskStore partitions by tenant_id.
        """
        tenant_dir = Path(root) / str(self.tenant_id)
        if not tenant_dir.exists():
            return 0, 0
        total = 0
        count = 0
        with os.scandir(tenant_dir) as it:
            for entry in it:
                if entry.is_file():
                    total += entry.stat().st_size
                    count += 1
        return total, count
