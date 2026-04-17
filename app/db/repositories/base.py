import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

T = TypeVar("T", bound=Base)


class TenantScopedRepository(Generic[T]):
    """Base repository that enforces tenant_id on every query and write.

    Subclasses set the `model` attribute. Any model used with this repository must
    have a `tenant_id` column. Use this for every data table except `Tenant` itself.
    """

    model: type[T]

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    def _tenant_filter(self):
        return self.model.tenant_id == self.tenant_id  # type: ignore[attr-defined]

    async def get(self, id: uuid.UUID) -> T | None:
        stmt = select(self.model).where(self.model.id == id, self._tenant_filter())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(self, *, limit: int = 100, offset: int = 0) -> list[T]:
        stmt = (
            select(self.model)
            .where(self._tenant_filter())
            .order_by(self.model.created_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add(self, obj: T) -> T:
        if getattr(obj, "tenant_id", None) != self.tenant_id:
            obj.tenant_id = self.tenant_id  # type: ignore[attr-defined]
        self.session.add(obj)
        await self.session.flush()
        return obj
