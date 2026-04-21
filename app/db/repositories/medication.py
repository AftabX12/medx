"""Medication repository — active-medication lookups with case-insensitive name matching."""
import uuid
from sqlalchemy import func, select

from app.db.models import Medication
from app.db.repositories.base import TenantScopedRepository


class MedicationRepository(TenantScopedRepository[Medication]):
    model = Medication

    async def list_for_patient(self, patient_id: uuid.UUID) -> list[Medication]:
        stmt = (
            select(Medication)
            .where(
                Medication.tenant_id == self.tenant_id,
                Medication.patient_id == patient_id,
            )
            .order_by(Medication.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_active_by_name(
        self, patient_id: uuid.UUID, name: str
    ) -> Medication | None:
        stmt = select(Medication).where(
            Medication.tenant_id == self.tenant_id,
            Medication.patient_id == patient_id,
            func.lower(Medication.name) == name.lower(),
            Medication.status == "active",
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
