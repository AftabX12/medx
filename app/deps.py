"""FastAPI dependency injection: session, authentication, and role guards.

Usage pattern:
    from app.deps import SessionDep, CurrentUser, AdminUser, PatientUser

    @router.get("/something")
    async def handler(session: SessionDep, user: CurrentUser): ...

Role hierarchy:
    admin       — full access including /admin/* routes
    doctor      — access to patient records, documents, AI pipeline
    patient     — access only to own portal data (/portal/*)

Unauthenticated requests raise HTTP 401; wrong-role requests raise HTTP 403.
Both are caught by the global exception handlers in main.py and redirected
to the appropriate login page.
"""

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
    """Return the raw JWT from the Authorization header or session cookie."""
    if bearer:
        return bearer
    return request.cookies.get(SESSION_COOKIE)


async def _load_user(session: AsyncSession, token: str) -> User | None:
    """Decode a JWT and load the corresponding active User from the database.

    Returns None if the token is invalid, the user does not exist, or the
    account is deactivated — callers treat None as an authentication failure.
    """
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
    """Require a valid session; raise 401 if missing or invalid."""
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
    """Load the current user from the session cookie; return None if not logged in.

    Used by routes that render differently for logged-in vs anonymous users
    rather than fully blocking anonymous access.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await _load_user(session, token)


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


async def require_admin(user: CurrentUser) -> User:
    """Guard: require role='admin'; raise 403 otherwise."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def require_patient(user: CurrentUser) -> User:
    """Guard: require role='patient' with a linked patient record; raise 403 otherwise."""
    if user.role != "patient":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient access required")
    if not user.patient_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No patient record linked")
    return user


async def require_clinician(user: CurrentUser) -> User:
    """Guard: require role='admin' or 'doctor'; raise 403 otherwise."""
    if user.role not in ("admin", "doctor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Clinician access required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
PatientUser = Annotated[User, Depends(require_patient)]
ClinicianUser = Annotated[User, Depends(require_clinician)]


__all__ = [
    "SESSION_COOKIE",
    "SessionDep",
    "CurrentUser",
    "OptionalUser",
    "AdminUser",
    "PatientUser",
    "ClinicianUser",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "require_patient",
    "require_clinician",
]
