import uuid

from sqlalchemy import select

from app.db.models import Extraction
from app.db.repositories.base import TenantScopedRepository


class ExtractionRepository(TenantScopedRepository[Extraction]):
    model = Extraction

    async def list_for_document(self, document_id: uuid.UUID) -> list[Extraction]:
        stmt = (
            select(Extraction)
            .where(
                Extraction.tenant_id == self.tenant_id,
                Extraction.document_id == document_id,
            )
            .order_by(Extraction.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
