# Use-case: проверка активности учётной записи (FR-011, US-001 A2).
from app.db import models
from app.use_cases.errors import DomainError


def ensure_active(user: models.User) -> None:
    """Деактивированный — токены не действуют (fail-closed)."""
    if user.is_deactivated:
        raise DomainError(
            status=401, code="UNAUTHENTICATED", title="Требуется аутентификация",
            detail="Учётная запись деактивирована",
        )
