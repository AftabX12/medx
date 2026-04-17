import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.db.repositories.audit import AuditRepository
from app.db.session import SessionLocal
from app.deps import SESSION_COOKIE
from app.logging import get_logger
from app.security import decode_access_token

log = get_logger(__name__)

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_PREFIXES = (
    "/auth/",
    "/healthz",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/login",
    "/register",
    "/logout",
)


class AuditMiddleware(BaseHTTPMiddleware):
    """Audit every mutating request made by an authenticated user.

    Write-auditing for `/auth/*` endpoints happens inline in those handlers because
    the tenant/user context is only established during the request itself.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        if request.method not in _WRITE_METHODS:
            return response
        path = request.url.path
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return response

        auth_header = request.headers.get("authorization", "")
        token: str | None = None
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1]
        else:
            token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return response
        try:
            payload = decode_access_token(token)
            user_id = uuid.UUID(payload["sub"])
            tenant_id = uuid.UUID(payload["tid"])
        except (ValueError, KeyError):
            return response

        resource_type = _derive_resource_type(path)
        try:
            async with SessionLocal() as session:
                repo = AuditRepository(session, tenant_id)
                await repo.record(
                    user_id=user_id,
                    action=request.method.lower(),
                    resource_type=resource_type,
                    method=request.method,
                    path=path,
                    status_code=response.status_code,
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("audit_write_failed", path=path, error=str(exc))

        return response


def _derive_resource_type(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    return parts[0] if parts else "unknown"
