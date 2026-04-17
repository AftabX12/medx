from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant


class TenantRepository:
    """Not tenant-scoped itself — Tenant IS the tenant boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_name(self, name: str) -> Tenant | None:
        stmt = select(Tenant).where(Tenant.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, name: str) -> Tenant:
        tenant = Tenant(name=name)
        self.session.add(tenant)
        await self.session.flush()
        return tenant
