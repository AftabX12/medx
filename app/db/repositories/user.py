from sqlalchemy import select

from app.db.models import User
from app.db.repositories.base import TenantScopedRepository


class UserRepository(TenantScopedRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(
            User.tenant_id == self.tenant_id,
            User.email == email.lower(),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
