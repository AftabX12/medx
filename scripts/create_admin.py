"""Create an admin user (and tenant if needed).

Usage (from the repo root):
    python -m scripts.create_admin

Or inside the Docker container:
    docker exec -it medx-app python -m scripts.create_admin

Prompts for tenant name, email, full name, and password.
If the tenant already exists it reuses it.
If the email already exists in that tenant the script exits cleanly.
"""

import asyncio
import getpass
import sys

from sqlalchemy import select

from app.db.models.tenant import Tenant, User
from app.db.session import SessionLocal
from app.security import hash_password


async def main() -> None:
    print("\n── MedX Admin Setup ──────────────────────────────────")

    tenant_name = input("Tenant name (e.g. 'General Hospital'): ").strip()
    if not tenant_name:
        print("Tenant name is required.")
        sys.exit(1)

    email = input("Admin email: ").strip().lower()
    if not email:
        print("Email is required.")
        sys.exit(1)

    full_name = input("Full name (optional): ").strip() or None

    password = getpass.getpass("Password: ")
    confirm  = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.")
        sys.exit(1)
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)

    async with SessionLocal() as session:
        # Get or create tenant
        result = await session.execute(select(Tenant).where(Tenant.name == tenant_name))
        tenant = result.scalars().first()
        if tenant is None:
            tenant = Tenant(name=tenant_name)
            session.add(tenant)
            await session.flush()
            print(f"\n  Created tenant: {tenant_name} ({tenant.id})")
        else:
            print(f"\n  Using existing tenant: {tenant_name} ({tenant.id})")

        # Check email not already taken in this tenant
        result = await session.execute(
            select(User).where(User.tenant_id == tenant.id, User.email == email)
        )
        if result.scalars().first() is not None:
            print(f"  User '{email}' already exists in this tenant.")
            sys.exit(0)

        user = User(
            tenant_id=tenant.id,
            email=email,
            full_name=full_name,
            password_hash=hash_password(password),
            role="admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()

    print(f"\n  Admin created: {email}")
    print(f"  Login at:      http://localhost:8000/admin/login\n")


if __name__ == "__main__":
    asyncio.run(main())
