import uuid

from app.db.models import AuditLog
from app.db.repositories.base import TenantScopedRepository


class AuditRepository(TenantScopedRepository[AuditLog]):
    model = AuditLog

    async def record(
        self,
        *,
        user_id: uuid.UUID | None,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        method: str | None = None,
        path: str | None = None,
        status_code: int | None = None,
        meta: dict | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            tenant_id=self.tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            method=method,
            path=path,
            status_code=status_code,
            meta=meta or {},
        )
        self.session.add(entry)
        await self.session.flush()
        return entry
