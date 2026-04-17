import uuid

from sqlalchemy import select

from app.db.models import Document
from app.db.repositories.base import TenantScopedRepository


class DocumentRepository(TenantScopedRepository[Document]):
    model = Document

    async def list_for_patient(
        self, patient_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> list[Document]:
        stmt = (
            select(Document)
            .where(
                Document.tenant_id == self.tenant_id,
                Document.patient_id == patient_id,
            )
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_hash(
        self, patient_id: uuid.UUID, file_hash: str
    ) -> Document | None:
        stmt = select(Document).where(
            Document.tenant_id == self.tenant_id,
            Document.patient_id == patient_id,
            Document.file_hash == file_hash,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
