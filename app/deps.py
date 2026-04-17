import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_session
from app.security import decode_access_token

SESSION_COOKIE = "medx_session"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _extract_token(request: Request, bearer: str | None) -> str | None:
    if bearer:
        return bearer
    return request.cookies.get(SESSION_COOKIE)


async def _load_user(session: AsyncSession, token: str) -> User | None:
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
        tenant_id = uuid.UUID(payload["tid"])
    except (ValueError, KeyError):
        return None
    stmt = select(User).where(
        User.id == user_id,
        User.tenant_id == tenant_id,
        User.is_active.is_(True),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_current_user(
    request: Request,
    session: SessionDep,
    bearer: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    token = _extract_token(request, bearer)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    user = await _load_user(session, token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    return user


async def get_optional_user(
    request: Request,
    session: SessionDep,
) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await _load_user(session, token)


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


__all__ = [
    "SESSION_COOKIE",
    "SessionDep",
    "CurrentUser",
    "OptionalUser",
    "get_current_user",
    "get_optional_user",
]
