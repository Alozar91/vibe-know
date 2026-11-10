# Общие хелперы сценарного слоя: права СА (FR-104), разбор UUID, выборка/валидация.
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


def get_group_or_404(db: Session, group_id: str, allow_deleted: bool = False) -> models.Group:
    g = db.execute(
        select(models.Group).where(models.Group.id == parse_uuid(group_id))
    ).scalar_one_or_none()
    if g is None or (g.is_deleted and not allow_deleted):
        raise not_found("Группа не найдена")
    return g


def validate_permissions(permissions: list[str]) -> list[models.PermissionCode]:
    """Каталог прав FR-106: неизвестный код — VALIDATION_ERROR (LLD §12.2)."""
    codes = []
    for p in set(permissions):
        try:
            codes.append(models.PermissionCode(p))
        except ValueError:
            raise DomainError(
                status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                detail=f"Неизвестное право: {p}",
            )
    return codes
