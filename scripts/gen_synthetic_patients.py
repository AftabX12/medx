"""Seed the DB with synthetic cardiology patients (and an admin user to log in with).

Usage:
    .venv/bin/python -m scripts.gen_synthetic_patients \\
        --tenant-name "Demo Clinic" --email demo@medx.example.com --count 20

No PHI, no AI calls — just pseudorandom demographics relevant to cardiology.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.db.models import Patient, Tenant, User
from app.db.session import SessionLocal
from app.security import hash_password

_FIRST_M = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Thomas"]
_FIRST_F = ["Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Sarah"]
_LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"]


async def ensure_tenant(session, name: str) -> Tenant:
    result = await session.execute(select(Tenant).where(Tenant.name == name))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name=name)
        session.add(tenant)
        await session.flush()
    return tenant


async def ensure_admin(
    session,
    tenant: Tenant,
    email: str,
    password: str,
    full_name: str | None,
) -> tuple[User, bool]:
    email_l = email.lower()
    result = await session.execute(
        select(User).where(User.tenant_id == tenant.id, User.email == email_l)
    )
    user = result.scalar_one_or_none()
    if user:
        return user, False
    user = User(
        tenant_id=tenant.id,
        email=email_l,
        full_name=full_name,
        password_hash=hash_password(password),
        role="admin",
    )
    session.add(user)
    await session.flush()
    return user, True


def _patient_payload(rng: random.Random) -> dict:
    sex = rng.choice(["M", "F"])
    given = rng.choice(_FIRST_M if sex == "M" else _FIRST_F)
    family = rng.choice(_LAST)
    age = rng.randint(45, 88)
    dob = date.today() - timedelta(days=age * 365 + rng.randint(0, 364))
    return {
        "mrn": f"MRN-{uuid.uuid4().hex[:8].upper()}",
        "given_name": given,
        "family_name": family,
        "date_of_birth": dob,
        "sex": sex,
        "demographics": {
            "bmi": round(rng.uniform(22.0, 38.0), 1),
            "smoker": rng.choice([True, False, False, False]),
            "hypertension": rng.choice([True, True, False]),
            "diabetes": rng.choice([True, False, False]),
            "family_history_cad": rng.choice([True, False]),
        },
    }


async def run(
    *,
    tenant_name: str,
    email: str,
    password: str,
    full_name: str | None,
    count: int,
    seed: int | None = None,
) -> None:
    rng = random.Random(seed)
    async with SessionLocal() as session:
        tenant = await ensure_tenant(session, tenant_name)
        user, created_user = await ensure_admin(
            session, tenant, email, password, full_name
        )
        for _ in range(count):
            patient = Patient(tenant_id=tenant.id, **_patient_payload(rng))
            session.add(patient)
        await session.commit()

    print(f"Tenant: {tenant_name} (id={tenant.id})")
    if created_user:
        print(f"Admin user created: {email} / {password}")
    else:
        print(f"Admin user already existed: {email} (password unchanged)")
    print(f"Seeded {count} patients.")
    print("\nLog in at http://127.0.0.1:8001/login with:")
    print(f"  Tenant:   {tenant_name}")
    print(f"  Email:    {email}")
    print(f"  Password: {password if created_user else '(your existing password)'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-name", default="Demo Clinic")
    parser.add_argument("--email", default="demo@medx.example.com")
    parser.add_argument("--password", default="password123")
    parser.add_argument("--full-name", default="Dr. Demo")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(
        run(
            tenant_name=args.tenant_name,
            email=args.email,
            password=args.password,
            full_name=args.full_name,
            count=args.count,
            seed=args.seed,
        )
    )


if __name__ == "__main__":
    main()
