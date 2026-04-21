"""Reconcile extracted patient demographics against the stored patient profile.

Strategy:
  - Field empty in DB, found in document  → auto-fill the patient record (safe)
  - Field matches in both                 → no action
  - Field differs (both have values)      → ReconcileFlag(kind="conflict",
                                            resource_type="patient_profile")
                                            for human review

Identity-critical fields (name, DOB) are NEVER auto-filled even if the DB field
is empty — they always go to human review, because a mismatch could mean a
wrong-patient association.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Patient, ReconcileFlag
from app.logging import get_logger

log = get_logger(__name__)

# These fields are auto-filled when the DB value is missing.
_AUTO_FILL_FIELDS = [
    "phone", "email",
    "address_line1", "address_line2", "city", "state", "zip_code", "country",
    "blood_type", "primary_physician",
    "insurance_provider", "insurance_id",
    "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
    "allergies_summary",
]

# These fields are flagged for review even when the DB value is missing,
# because they are identity-critical or clinically sensitive.
_REVIEW_FIELDS = [
    "given_name", "family_name", "date_of_birth", "sex", "mrn",
]

# Severity rules: field → severity when a conflict or new-data flag is raised.
# Tier is always 2 (LLM-derived from document extraction).
_FIELD_SEVERITY: dict[str, str] = {
    "given_name": "critical",
    "family_name": "critical",
    "date_of_birth": "critical",
    "mrn": "critical",
    "blood_type": "critical",
    "sex": "warning",
    "allergies_summary": "warning",
    "phone": "info",
    "email": "info",
    "address_line1": "info",
    "address_line2": "info",
    "city": "info",
    "state": "info",
    "zip_code": "info",
    "country": "info",
    "primary_physician": "info",
    "insurance_provider": "info",
    "insurance_id": "info",
    "emergency_contact_name": "info",
    "emergency_contact_phone": "info",
    "emergency_contact_relation": "info",
}


def _normalise(v: object) -> str:
    return str(v or "").strip().lower()


async def reconcile_patient_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    extraction_id: uuid.UUID,
    extracted: dict,
) -> int:
    """Compare *extracted* demographics against the stored patient.

    Returns the number of reconcile flags created.
    """
    if not extracted:
        return 0

    patient: Patient | None = await session.get(Patient, patient_id)
    if patient is None:
        return 0

    flags_created = 0

    # ── Auto-fill fields ──────────────────────────────────────────────────────
    changed = False
    for field in _AUTO_FILL_FIELDS:
        doc_val = extracted.get(field)
        if not doc_val:
            continue
        db_val = getattr(patient, field, None)
        if not db_val:
            # Empty in DB → fill from document
            setattr(patient, field, doc_val)
            changed = True
            log.info(
                "profile_auto_filled",
                patient_id=str(patient_id),
                field=field,
                value=str(doc_val)[:80],
            )
        elif _normalise(db_val) != _normalise(doc_val):
            # Both have values and they differ → flag for review
            flag = ReconcileFlag(
                tenant_id=tenant_id,
                patient_id=patient_id,
                document_id=document_id,
                kind="conflict",
                resource_type="patient_profile",
                existing_id=None,
                new_extraction_id=extraction_id,
                details={
                    "field": field,
                    "existing_value": str(db_val),
                    "document_value": str(doc_val),
                },
                severity=_FIELD_SEVERITY.get(field, "info"),
                tier=2,
            )
            session.add(flag)
            flags_created += 1

    # ── Identity / review-only fields ─────────────────────────────────────────
    for field in _REVIEW_FIELDS:
        doc_val = extracted.get(field)
        if not doc_val:
            continue
        db_val = getattr(patient, field, None)
        if db_val and _normalise(db_val) != _normalise(str(doc_val)):
            flag = ReconcileFlag(
                tenant_id=tenant_id,
                patient_id=patient_id,
                document_id=document_id,
                kind="conflict",
                resource_type="patient_profile",
                existing_id=None,
                new_extraction_id=extraction_id,
                details={
                    "field": field,
                    "existing_value": str(db_val),
                    "document_value": str(doc_val),
                    "review_required": True,
                },
                severity=_FIELD_SEVERITY.get(field, "warning"),
                tier=2,
            )
            session.add(flag)
            flags_created += 1
        elif not db_val:
            # Missing identity field — flag for human to confirm before filling
            flag = ReconcileFlag(
                tenant_id=tenant_id,
                patient_id=patient_id,
                document_id=document_id,
                kind="new_data",
                resource_type="patient_profile",
                existing_id=None,
                new_extraction_id=extraction_id,
                details={
                    "field": field,
                    "existing_value": None,
                    "document_value": str(doc_val),
                    "review_required": True,
                },
                severity=_FIELD_SEVERITY.get(field, "warning"),
                tier=2,
            )
            session.add(flag)
            flags_created += 1

    if changed:
        await session.flush()

    return flags_created
