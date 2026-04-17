"""Phase 0 exit criterion: register, log in, create a tenant+patient, verify audit."""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import AuditLog, Patient, Tenant, User
from app.db.session import SessionLocal


async def test_phase0_exit_criterion(client):
    register_body = {
        "tenant_name": "Phase0 Clinic",
        "email": "doc@phase0.example.com",
        "password": "password123",
        "full_name": "Dr. Phase Zero",
    }
    r = await client.post("/auth/register", json=register_body)
    assert r.status_code == 201, r.text
    assert r.json()["access_token"]

    # Re-register same tenant should conflict
    r = await client.post("/auth/register", json=register_body)
    assert r.status_code == 409

    r = await client.post(
        "/auth/login",
        json={
            "tenant_name": "Phase0 Clinic",
            "email": "doc@phase0.example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Unauthenticated patient create must fail
    r = await client.post("/patients", json={"mrn": "M1", "given_name": "X", "family_name": "Y"})
    assert r.status_code == 401

    # Authenticated create succeeds
    r = await client.post(
        "/patients",
        headers=headers,
        json={
            "mrn": "MRN-0001",
            "given_name": "Alice",
            "family_name": "Rivera",
            "sex": "F",
            "date_of_birth": "1962-04-10",
            "demographics": {"bmi": 27.5, "hypertension": True},
        },
    )
    assert r.status_code == 201, r.text
    patient_id = r.json()["id"]

    # Duplicate MRN conflicts
    r = await client.post(
        "/patients",
        headers=headers,
        json={"mrn": "MRN-0001", "given_name": "Dup", "family_name": "Patient"},
    )
    assert r.status_code == 409

    # Fetch the patient back
    r = await client.get(f"/patients/{patient_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["mrn"] == "MRN-0001"

    # List
    r = await client.get("/patients", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Inspect DB-side effects
    async with SessionLocal() as session:
        tenants = (await session.execute(select(Tenant))).scalars().all()
        users = (await session.execute(select(User))).scalars().all()
        patients = (await session.execute(select(Patient))).scalars().all()
        audits = (await session.execute(select(AuditLog))).scalars().all()

    assert len(tenants) == 1
    assert tenants[0].name == "Phase0 Clinic"
    assert len(users) == 1
    assert users[0].tenant_id == tenants[0].id
    assert len(patients) == 1
    assert patients[0].tenant_id == tenants[0].id

    actions = {a.action for a in audits}
    # register + login are written inline by handlers; POST /patients by middleware
    assert "register" in actions
    assert "login" in actions
    assert "post" in actions
    assert all(a.tenant_id == tenants[0].id for a in audits)


async def test_cross_tenant_isolation(client):
    r = await client.post(
        "/auth/register",
        json={
            "tenant_name": "Tenant A",
            "email": "a@iso.example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 201
    token_a = r.json()["access_token"]

    r = await client.post(
        "/auth/register",
        json={
            "tenant_name": "Tenant B",
            "email": "b@iso.example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 201
    token_b = r.json()["access_token"]

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    r = await client.post(
        "/patients",
        headers=headers_a,
        json={"mrn": "A-1", "given_name": "A", "family_name": "One"},
    )
    assert r.status_code == 201
    pid_a = r.json()["id"]

    # Tenant B cannot see Tenant A's patient
    r = await client.get(f"/patients/{pid_a}", headers=headers_b)
    assert r.status_code == 404

    # Tenant B's list is empty
    r = await client.get("/patients", headers=headers_b)
    assert r.status_code == 200
    assert r.json() == []
