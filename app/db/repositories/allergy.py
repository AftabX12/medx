import uuid

from sqlalchemy import func, select

from app.db.models import Allergy
from app.db.repositories.base import TenantScopedRepository


class AllergyRepository(TenantScopedRepository[Allergy]):
    model = Allergy

    async def list_for_patient(self, patient_id: uuid.UUID) -> list[Allergy]:
        stmt = (
            select(Allergy)
            .where(
                Allergy.tenant_id == self.tenant_id,
                Allergy.patient_id == patient_id,
            )
            .order_by(Allergy.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_substance(
        self, patient_id: uuid.UUID, substance: str
    ) -> Allergy | None:
        stmt = select(Allergy).where(
            Allergy.tenant_id == self.tenant_id,
            Allergy.patient_id == patient_id,
            func.lower(Allergy.substance) == substance.lower(),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
