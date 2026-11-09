# Вспомогательные операции сценарного слоя: проверка прав СА (FR-104) и разбор UUID.
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.errors import DomainError, access_denied, not_found


def require_super(is_super: bool) -> None:
    """FR-104: операции управления — только системный администратор."""
    if not is_super:
        raise access_denied("Доступ только для системного администратора")


def parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


def get_user_or_404(db: Session, user_id: str) -> models.User:
    u = db.execute(
        select(models.User).where(models.User.id == parse_uuid(user_id))
    ).scalar_one_or_none()
    if u is None:
        raise not_found("Пользователь не найден")
    return u


def get_role_or_404(db: Session, role_id: str) -> models.Role:
    r = db.execute(
        select(models.Role).where(models.Role.id == parse_uuid(role_id))
    ).scalar_one_or_none()
    if r is None:
        raise not_found("Роль не найдена")
    return r
