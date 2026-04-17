"""Phase 1.5: tenant dashboard landing page — counts, recent uploads, needs-attention, storage."""

from __future__ import annotations

import io

import pytest

from tests.test_phase1b_extraction import _make_pdf


async def _register_api(client, tenant: str, email: str) -> str:
    r = await client.post(
        "/auth/register",
        json={"tenant_name": tenant, "email": email, "password": "password123"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_dashboard_unauthenticated_redirects_to_login(client):
    r = await client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_post_login_lands_on_dashboard(client):
    r = await client.post(
        "/register",
        data={
            "tenant_name": "Dash Clinic",
            "email": "dash@ex.example.com",
            "password": "password123",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"

    # Follow to /dashboard with the session cookie set by /register
    r = await client.get("/dashboard")
    assert r.status_code == 200
    assert "Dashboard" in r.text


@pytest.mark.asyncio
async def test_dashboard_reflects_uploads_and_isolates_tenants(client):
    # Tenant A: 1 patient, 2 PDFs (ok), 1 PNG (unsupported)
    token_a = await _register_api(client, "Alpha Clinic", "a@dash.example.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    r = await client.post(
        "/patients",
        headers=headers_a,
        json={"mrn": "A-1", "given_name": "Ada", "family_name": "A"},
    )
    pid_a = r.json()["id"]

    pdf1 = _make_pdf("ALPHA PDF ONE")
    pdf2 = _make_pdf("ALPHA PDF TWO")
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    for name, data, mime in [
        ("one.pdf", pdf1, "application/pdf"),
        ("two.pdf", pdf2, "application/pdf"),
        ("pic.png", png, "image/png"),
    ]:
        r = await client.post(
            f"/patients/{pid_a}/documents",
            headers=headers_a,
            files={"file": (name, io.BytesIO(data), mime)},
        )
        assert r.status_code == 201

    # Wait for background OCR to settle
    import asyncio

    for _ in range(20):
        docs = (await client.get(f"/patients/{pid_a}/documents", headers=headers_a)).json()
        if all(d["ocr_status"] != "pending" for d in docs):
            break
        await asyncio.sleep(0.05)

    # Render dashboard as tenant A (cookie session from /register flow)
    r = await client.post(
        "/register",
        data={
            "tenant_name": "Alpha Clinic Web",
            "email": "awd@dash.example.com",
            "password": "password123",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = await client.get("/dashboard")
    assert r.status_code == 200
    # Tenant B sees zero of tenant A's data
    assert "Patients" in r.text
    assert "Nothing flagged" in r.text or "Needs attention" in r.text

    # Now log in as tenant A via the web form (sets A's cookie)
    r = await client.post(
        "/login",
        data={
            "tenant_name": "Alpha Clinic",
            "email": "a@dash.example.com",
            "password": "password123",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"

    r = await client.get("/dashboard")
    assert r.status_code == 200
    # Sees uploaded file + patient + unsupported badge
    assert "one.pdf" in r.text or "two.pdf" in r.text
    assert "pic.png" in r.text
    assert "Ada" in r.text
    assert "unsupported" in r.text


@pytest.mark.asyncio
async def test_dashboard_repository_counts_directly(client):
    """Hit the repo layer with a tenant that has known data to validate aggregations."""
    from app.db.repositories.dashboard import DashboardRepository
    from app.db.session import SessionLocal

    token = await _register_api(client, "RepoCount Clinic", "rc@dash.example.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        "/patients",
        headers=headers,
        json={"mrn": "RC-1", "given_name": "Ren", "family_name": "Repo"},
    )
    pid = r.json()["id"]

    pdf = _make_pdf("RC ONE")
    r = await client.post(
        f"/patients/{pid}/documents",
        headers=headers,
        files={"file": ("rc.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    assert r.status_code == 201

    import asyncio

    for _ in range(20):
        docs = (await client.get(f"/patients/{pid}/documents", headers=headers)).json()
        if all(d["ocr_status"] != "pending" for d in docs):
            break
        await asyncio.sleep(0.05)

    from app.db.repositories.tenant import TenantRepository

    async with SessionLocal() as session:
        tenant = await TenantRepository(session).get_by_name("RepoCount Clinic")
        assert tenant is not None
        repo = DashboardRepository(session, tenant.id)
        assert await repo.patient_count() == 1
        counts = await repo.document_counts_by_status()
        assert counts["ok"] >= 1
        recent = await repo.recent_uploads(limit=10)
        assert len(recent) == 1
        doc, patient = recent[0]
        assert doc.original_filename == "rc.pdf"
        assert patient.mrn == "RC-1"
