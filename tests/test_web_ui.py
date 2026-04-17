"""Smoke tests for the HTMX/Jinja UI: register -> patient list -> create -> detail."""

from __future__ import annotations

import re


async def test_web_ui_happy_path(client):
    # Anonymous root redirects to login
    r = await client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"

    # Register through the form
    r = await client.post(
        "/register",
        data={
            "tenant_name": "Web UI Clinic",
            "email": "doc@webui.example.com",
            "password": "password123",
            "full_name": "Dr. Web",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/dashboard"
    assert "medx_session=" in r.headers.get("set-cookie", "")

    # Patient list is empty
    r = await client.get("/patients/ui")
    assert r.status_code == 200
    assert "No patients yet" in r.text

    # Create a patient
    r = await client.post(
        "/patients/ui",
        data={
            "mrn": "WEB-001",
            "given_name": "Alex",
            "family_name": "Doe",
            "sex": "F",
            "date_of_birth": "1970-01-02",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    # Redirects to /patients/ui/{id}
    assert re.match(r"^/patients/ui/[0-9a-f-]{36}$", r.headers["location"])

    # Follow to detail
    detail = await client.get(r.headers["location"])
    assert detail.status_code == 200
    assert "WEB-001" in detail.text
    assert "Alex Doe" in detail.text

    # Duplicate MRN re-renders the form with an error
    r = await client.post(
        "/patients/ui",
        data={
            "mrn": "WEB-001",
            "given_name": "Alex",
            "family_name": "Dup",
        },
    )
    assert r.status_code == 200
    assert "already exists" in r.text

    # Logout clears the cookie
    r = await client.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"

    # After logout, /patients/ui redirects to /login
    r = await client.get("/patients/ui", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


async def test_web_login_bad_credentials(client):
    r = await client.post(
        "/login",
        data={
            "tenant_name": "Nonexistent Clinic",
            "email": "nobody@webui.example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 200
    assert "Invalid credentials" in r.text
