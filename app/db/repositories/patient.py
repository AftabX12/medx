from app.db.models import Patient
from app.db.repositories.base import TenantScopedRepository


class PatientRepository(TenantScopedRepository[Patient]):
    model = Patient
