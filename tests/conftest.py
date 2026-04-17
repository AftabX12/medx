"""Test config: points the app at a throwaway SQLite file *before* app imports."""

from __future__ import annotations

import os
from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent
_TEST_DB = _TEST_DIR / ".test.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()
_TEST_UPLOADS = _TEST_DIR / ".test-uploads"
if _TEST_UPLOADS.exists():
    import shutil

    shutil.rmtree(_TEST_UPLOADS)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret-phase0"
os.environ["LOCAL_STORE_PATH"] = str(_TEST_UPLOADS)

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
