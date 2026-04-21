"""ReconcileFlag repository — open/resolved conflict flags raised by the AI pipeline."""
import uuid

from sqlalchemy import select

from app.db.models import ReconcileFlag
from app.db.repositories.base import TenantScopedRepository


class ReconcileFlagRepository(TenantScopedRepository[ReconcileFlag]):
    model = ReconcileFlag

    async def list_for_patient(
        self, patient_id: uuid.UUID, *, resolved: bool | None = False
    ) -> list[ReconcileFlag]:
        stmt = select(ReconcileFlag).where(
            ReconcileFlag.tenant_id == self.tenant_id,
            ReconcileFlag.patient_id == patient_id,
        )
        if resolved is not None:
            stmt = stmt.where(ReconcileFlag.resolved == resolved)
        stmt = stmt.order_by(ReconcileFlag.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
