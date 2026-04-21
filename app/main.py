"""MedX application factory and lifespan.

This module wires together all FastAPI routers, middleware, exception handlers,
and the background worker queue. Import `app` directly for ASGI deployment:

    uvicorn app.main:app
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse

from sqlalchemy import select

from app.api import auth, chat, documents, extractions, health, patients
from app.audit.middleware import AuditMiddleware
from app.config import get_settings
from app.db.models.tenant import Tenant, User
from app.db.session import SessionLocal
from app.logging import configure_logging
from app.queue import get_queue
from app.security import hash_password
from app.web.routes import router as web_router
from app.web.portal_routes import router as portal_router, patient_router


async def _seed_admin() -> None:
    """Create the default admin user on first startup if not already present."""
    s = get_settings()
    async with SessionLocal() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.name == s.seed_tenant_name))
        ).scalars().first()
        if tenant is None:
            tenant = Tenant(name=s.seed_tenant_name)
            session.add(tenant)
            await session.flush()

        exists = (
            await session.execute(
                select(User).where(User.tenant_id == tenant.id, User.email == s.seed_admin_email)
            )
        ).scalars().first()
        if exists is None:
            session.add(User(
                tenant_id=tenant.id,
                email=s.seed_admin_email,
                full_name=s.seed_admin_name,
                password_hash=hash_password(s.seed_admin_password),
                role="admin",
                is_active=True,
            ))
            await session.commit()


def _login_redirect_for(path: str) -> RedirectResponse:
    """Return a redirect to the role-appropriate login page based on the request path.

    Called by 401/403 exception handlers so unauthenticated users land on the
    correct login page rather than seeing a raw error response.
    """
    if path.startswith("/admin"):
        return RedirectResponse("/admin/login", status_code=303)
    if path.startswith("/portal") or path.startswith("/patient"):
        return RedirectResponse("/patient/login", status_code=303)
    return RedirectResponse("/doctor/login", status_code=303)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: start the worker queue on startup, drain it on shutdown.

    The queue re-enqueues any documents stuck in ocr_status='pending' from a
    previous run, so no work is silently lost across restarts.
    """
    configure_logging()
    settings = get_settings()
    await _seed_admin()
    queue = get_queue()
    await queue.start(concurrency=settings.queue_max_concurrency)
    try:
        yield
    finally:
        await queue.stop()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Registers middleware, exception handlers, and all routers. Separated from
    module-level `app` assignment so tests can call `create_app()` independently.
    """
    settings = get_settings()
    app = FastAPI(
        title="MedX",
        version="0.1.0",
        debug=settings.app_debug,
        lifespan=lifespan,
    )
    app.add_middleware(AuditMiddleware)

    @app.exception_handler(401)
    async def _handle_401(request: Request, exc: HTTPException):
        """Redirect unauthenticated requests to the appropriate login page."""
        return _login_redirect_for(request.url.path)

    @app.exception_handler(403)
    async def _handle_403(request: Request, exc: HTTPException):
        """Redirect forbidden requests (wrong role) to the appropriate login page."""
        return _login_redirect_for(request.url.path)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(web_router)
    app.include_router(patients.router)
    app.include_router(documents.router)
    app.include_router(extractions.router)
    app.include_router(chat.router)
    app.include_router(portal_router)
    app.include_router(patient_router)
    return app


app = create_app()
