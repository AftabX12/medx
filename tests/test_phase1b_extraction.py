"""Phase 1b: pypdf text extraction runs as a background task after upload."""

from __future__ import annotations

import io

import pytest


def _make_pdf(text: str) -> bytes:
    """Hand-rolled minimal valid PDF with a single text string (no ML, no OCR)."""
    content_stream = f"BT /F1 12 Tf 100 700 Td ({text}) Tj ET".encode("latin-1")
    content_obj = (
        b"<</Length "
        + str(len(content_stream)).encode()
        + b">>\nstream\n"
        + content_stream
        + b"\nendstream"
    )
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        content_obj,
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (
        f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return pdf


async def _register(client, tenant: str, email: str) -> str:
    r = await client.post(
        "/auth/register",
        json={"tenant_name": tenant, "email": email, "password": "password123"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_pdf_text_extracted_after_upload(client):
    token = await _register(client, "Extract Clinic", "e@ex.example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Create patient
    r = await client.post(
        "/patients",
        headers=headers,
        json={"mrn": "EXT-001", "given_name": "Erin", "family_name": "Extract"},
    )
    pid = r.json()["id"]

    pdf_bytes = _make_pdf("CARDIOLOGY LAB REPORT LDL 140")
    files = {"file": ("labs.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = await client.post(f"/patients/{pid}/documents", headers=headers, files=files)
    assert r.status_code == 201
    doc_id = r.json()["id"]

    # Background task runs before ASGITransport returns, but be defensive.
    for _ in range(20):
        r = await client.get(f"/documents/{doc_id}", headers=headers)
        if r.json()["ocr_status"] != "pending":
            break
        import asyncio

        await asyncio.sleep(0.05)

    r = await client.get(f"/documents/{doc_id}", headers=headers)
    assert r.json()["ocr_status"] == "ok", r.json()

    r = await client.get(f"/documents/{doc_id}/text", headers=headers)
    assert r.status_code == 200
    assert "CARDIOLOGY LAB REPORT" in r.text
    assert "LDL 140" in r.text


@pytest.mark.asyncio
async def test_image_upload_marked_unsupported(client):
    token = await _register(client, "Image Clinic", "i@ex.example.com")
    headers = {"Authorization": f"Bearer {token}"}
    r = await client.post(
        "/patients",
        headers=headers,
        json={"mrn": "IMG-001", "given_name": "Iris", "family_name": "Image"},
    )
    pid = r.json()["id"]

    # 1x1 transparent PNG
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    files = {"file": ("pic.png", io.BytesIO(png), "image/png")}
    r = await client.post(f"/patients/{pid}/documents", headers=headers, files=files)
    assert r.status_code == 201
    doc_id = r.json()["id"]

    for _ in range(20):
        r = await client.get(f"/documents/{doc_id}", headers=headers)
        if r.json()["ocr_status"] != "pending":
            break
        import asyncio

        await asyncio.sleep(0.05)

    assert r.json()["ocr_status"] == "unsupported"


@pytest.mark.asyncio
async def test_document_viewer_page_renders(client):
    r = await client.post(
        "/register",
        data={
            "tenant_name": "Viewer Clinic",
            "email": "v@ex.example.com",
            "password": "password123",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = await client.post(
        "/patients/ui",
        data={"mrn": "V-1", "given_name": "Vik", "family_name": "View"},
        follow_redirects=False,
    )
    pid = r.headers["location"].rsplit("/", 1)[-1]

    pdf_bytes = _make_pdf("VIEWER TEST")
    files = {"file": ("v.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = await client.post(f"/patients/ui/{pid}/documents", files=files)
    assert r.status_code == 200

    # Scrape the doc id from the panel HTML
    import re

    m = re.search(r"/documents/ui/([0-9a-f-]{36})", r.text)
    assert m, r.text
    doc_id = m.group(1)

    r = await client.get(f"/documents/ui/{doc_id}")
    assert r.status_code == 200
    assert "Extracted text" in r.text
    assert "Original" in r.text
