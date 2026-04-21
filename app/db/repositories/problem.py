"""Problem repository — patient problem list with case-insensitive label deduplication."""
import uuid

from sqlalchemy import func, select

from app.db.models import Problem
from app.db.repositories.base import TenantScopedRepository


class ProblemRepository(TenantScopedRepository[Problem]):
    model = Problem

    async def list_for_patient(self, patient_id: uuid.UUID) -> list[Problem]:
        stmt = (
            select(Problem)
            .where(
                Problem.tenant_id == self.tenant_id,
                Problem.patient_id == patient_id,
            )
            .order_by(Problem.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_label(
        self, patient_id: uuid.UUID, label: str
    ) -> Problem | None:
        stmt = select(Problem).where(
            Problem.tenant_id == self.tenant_id,
            Problem.patient_id == patient_id,
            func.lower(Problem.label) == label.lower(),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
