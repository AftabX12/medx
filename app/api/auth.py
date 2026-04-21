"""Auth REST API — tenant registration and JWT login for doctor/admin accounts."""
from fastapi import APIRouter, HTTPException, status

from app.db.models import User
from app.db.repositories.audit import AuditRepository
from app.db.repositories.tenant import TenantRepository
from app.db.repositories.user import UserRepository
from app.deps import SessionDep
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: SessionDep) -> TokenResponse:
    tenant_repo = TenantRepository(session)
    if await tenant_repo.get_by_name(body.tenant_name):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="tenant already exists")

    tenant = await tenant_repo.create(body.tenant_name)

    user = User(
        tenant_id=tenant.id,
        email=body.email.lower(),
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role="doctor",
    )
    session.add(user)
    await session.flush()

    audit = AuditRepository(session, tenant.id)
    await audit.record(
        user_id=user.id,
        action="register",
        resource_type="tenant",
        resource_id=str(tenant.id),
        method="POST",
        path="/auth/register",
        status_code=201,
    )

    await session.commit()

    token = create_access_token(user_id=user.id, tenant_id=tenant.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: SessionDep) -> TokenResponse:
    tenant_repo = TenantRepository(session)
    tenant = await tenant_repo.get_by_name(body.tenant_name)
    if not tenant:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    user_repo = UserRepository(session, tenant.id)
    user = await user_repo.get_by_email(body.email)
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    audit = AuditRepository(session, tenant.id)
    await audit.record(
        user_id=user.id,
        action="login",
        resource_type="session",
        method="POST",
        path="/auth/login",
        status_code=200,
    )
    await session.commit()

    token = create_access_token(user_id=user.id, tenant_id=tenant.id)
    return TokenResponse(access_token=token)
