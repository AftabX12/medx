"""Authentication helpers: password hashing and JWT token management.

Passwords are hashed with bcrypt (work factor from bcrypt.gensalt default).
JWTs carry `sub` (user_id) and `tid` (tenant_id) claims; expiry is controlled
by `settings.jwt_expire_minutes`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt and return the encoded digest."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Return True if `password` matches the stored bcrypt hash.

    Returns False on any bcrypt error (malformed hash, encoding issue) rather
    than raising, so callers can treat it as a failed authentication uniformly.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    """Create a signed JWT for the given user and tenant.

    Claims:
        sub — user UUID (str)
        tid — tenant UUID (str)
        iat — issued-at (Unix timestamp)
        exp — expiry (iat + jwt_expire_minutes)
    """
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT, returning its payload dict.

    Raises ValueError (wrapping the underlying JWTError) if the token is
    expired, tampered, or otherwise invalid. Callers should treat ValueError
    as an authentication failure.
    """
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError(f"invalid token: {exc}") from exc
