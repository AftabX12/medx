"""Phase 1a: document upload + list + retrieval + tenant isolation."""

from __future__ import annotations

import io


_FAKE_PDF = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    b"xref\n0 4\n0000000000 65535 f \ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
)


async def _register(client, tenant: str, email: str) -> str:
    r = await client.post(
        "/auth/register",
        json={"tenant_name": tenant, "email": email, "password": "password123"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _create_patient(client, headers, mrn: str = "DOC-001") -> str:
    r = await client.post(
        "/patients",
        headers=headers,
        json={"mrn": mrn, "given_name": "Pat", "family_name": "Test"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_upload_list_retrieve(client):
    token = await _register(client, "Docs Clinic", "docs@ex.example.com")
    headers = {"Authorization": f"Bearer {token}"}
    pid = await _create_patient(client, headers)

    # Upload
    files = {"file": ("labs.pdf", io.BytesIO(_FAKE_PDF), "application/pdf")}
    r = await client.post(f"/patients/{pid}/documents", headers=headers, files=files)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["ocr_status"] == "pending"
    assert doc["original_filename"] == "labs.pdf"
    assert doc["mime_type"] == "application/pdf"
    assert len(doc["file_hash"]) == 64

    # List
    r = await client.get(f"/patients/{pid}/documents", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Get one
    r = await client.get(f"/documents/{doc['id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == doc["id"]

    # Raw download
    r = await client.get(f"/documents/{doc['id']}/raw", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF")

    # Dedupe: uploading the same bytes again returns the same document ID
    files2 = {"file": ("labs-again.pdf", io.BytesIO(_FAKE_PDF), "application/pdf")}
    r = await client.post(f"/patients/{pid}/documents", headers=headers, files=files2)
    assert r.status_code == 201
    assert r.json()["id"] == doc["id"]
    r = await client.get(f"/patients/{pid}/documents", headers=headers)
    assert len(r.json()) == 1

    # Reject unsupported type
    files3 = {"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")}
    r = await client.post(f"/patients/{pid}/documents", headers=headers, files=files3)
    assert r.status_code == 415


async def test_documents_tenant_isolation(client):
    token_a = await _register(client, "Tenant DocsA", "a@docs.example.com")
    token_b = await _register(client, "Tenant DocsB", "b@docs.example.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    pid_a = await _create_patient(client, headers_a, mrn="A-1")
    files = {"file": ("labs.pdf", io.BytesIO(_FAKE_PDF), "application/pdf")}
    r = await client.post(f"/patients/{pid_a}/documents", headers=headers_a, files=files)
    assert r.status_code == 201
    doc_id = r.json()["id"]

    # Tenant B cannot list A's patient documents, get the doc, or download it
    assert (await client.get(f"/patients/{pid_a}/documents", headers=headers_b)).status_code == 404
    assert (await client.get(f"/documents/{doc_id}", headers=headers_b)).status_code == 404
    assert (await client.get(f"/documents/{doc_id}/raw", headers=headers_b)).status_code == 404


async def test_upload_via_web_ui(client):
    # Register through the web form to get a session cookie
    r = await client.post(
        "/register",
        data={
            "tenant_name": "Web Docs Clinic",
            "email": "w@docs.example.com",
            "password": "password123",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Create a patient via the web form
    r = await client.post(
        "/patients/ui",
        data={"mrn": "WEB-DOC-1", "given_name": "Pat", "family_name": "Web"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    patient_url = r.headers["location"]  # /patients/ui/<uuid>
    patient_id = patient_url.rsplit("/", 1)[-1]

    # Upload a PDF via the form's POST target; response is an HTMX fragment
    files = {"file": ("labs.pdf", io.BytesIO(_FAKE_PDF), "application/pdf")}
    r = await client.post(f"/patients/ui/{patient_id}/documents", files=files)
    assert r.status_code == 200
    assert "labs.pdf" in r.text
    assert "pending" in r.text

    # The polling GET returns the same partial
    r = await client.get(f"/patients/ui/{patient_id}/documents")
    assert r.status_code == 200
    assert "labs.pdf" in r.text
