"""Observation repository — lab results and vital signs, ordered by effective_date."""
import uuid

from sqlalchemy import select

from app.db.models import Observation
from app.db.repositories.base import TenantScopedRepository


class ObservationRepository(TenantScopedRepository[Observation]):
    model = Observation

    async def list_for_patient(
        self, patient_id: uuid.UUID, *, limit: int = 500, offset: int = 0
    ) -> list[Observation]:
        stmt = (
            select(Observation)
            .where(
                Observation.tenant_id == self.tenant_id,
                Observation.patient_id == patient_id,
            )
            .order_by(Observation.effective_date.desc().nullslast())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
