from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, documents, health, patients
from app.audit.middleware import AuditMiddleware
from app.config import get_settings
from app.logging import configure_logging
from app.web.routes import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MedX",
        version="0.1.0",
        debug=settings.app_debug,
        lifespan=lifespan,
    )
    app.add_middleware(AuditMiddleware)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(web_router)
    app.include_router(patients.router)
    app.include_router(documents.router)
    return app


app = create_app()
