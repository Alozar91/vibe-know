# Сценарии ролей-шаблонов: CRUD + клонирование (LLD §12.3, FR-008, FR-105, US-043).
import uuid as uuid_mod

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import get_role_or_404, parse_uuid, require_super
from app.use_cases.errors import DomainError, name_conflict, domain_rule_violation

VIRTUAL_ALL_USERS = "Все пользователи"
SUPERUSER_ROLE_NAME = "Системный администратор"


def to_out(r: models.Role) -> dict:
    perms = sorted(
        p.permission.value if hasattr(p.permission, "value") else str(p.permission)
        for p in r.permissions
    )
    return {
        "id": str(r.id),
        "name": r.name,
        "is_virtual_all_users": r.is_virtual_all_users,
        "permissions": perms,
    }


def list_roles(db: Session) -> list[dict]:
    """Шаблоны ролей (FR-008): базовые + клоны + виртуальная «Все пользователи»."""
    rows = db.execute(select(models.Role).order_by(models.Role.created_at)).scalars().all()
    return [to_out(r) for r in rows]


def _validate_permissions(permissions: list[str]) -> list[models.PermissionCode]:
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


def _ensure_name_free(db: Session, name: str, except_id: uuid_mod.UUID | None = None) -> None:
    stmt = select(models.Role).where(models.Role.name == name)
    if except_id is not None:
        stmt = stmt.where(models.Role.id != except_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        raise name_conflict("Роль с таким названием уже существует")


def create_role(db: Session, is_super: bool, name: str, permissions: list[str]) -> dict:
    """Создание шаблона (FR-008; правки — US-043)."""
    require_super(is_super)
    _ensure_name_free(db, name)
    role = models.Role(name=name)
    for code in _validate_permissions(permissions):
        role.permissions.append(models.RolePermission(permission=code))
    db.add(role)
    db.commit()
    return to_out(role)


def update_role(
    db: Session, is_super: bool, role_id: str, name: str | None, permissions: list[str] | None
) -> dict:
    """Правка состава/названия шаблона (FR-008, US-043 шаг 2).

    Не влияет на уже созданные снапшоты (FR-100) — снапшоты этапа 4.
    """
    require_super(is_super)
    role = get_role_or_404(db, role_id)
    if role.is_virtual_all_users and permissions is not None:
        raise domain_rule_violation(
            409, "Виртуальная роль «Все пользователи» не имеет состава прав"
        )
    if name is not None and name != role.name:
        _ensure_name_free(db, name, except_id=role.id)
        role.name = name
    if permissions is not None:
        role.permissions.clear()
        for code in _validate_permissions(permissions):
            role.permissions.append(models.RolePermission(permission=code))
    db.commit()
    return to_out(role)


def delete_role(db: Session, is_super: bool, role_id: str) -> None:
    """Удаление шаблона (FR-008)."""
    require_super(is_super)
    role = get_role_or_404(db, role_id)
    db.delete(role)
    db.commit()


def clone_role(db: Session, is_super: bool, role_id: str) -> dict:
    """Клонирование: копия набора прав шаблона (FR-105, US-003 шаг 2)."""
    require_super(is_super)
    src = get_role_or_404(db, role_id)
    if src.is_virtual_all_users:
        raise domain_rule_violation(409, "Виртуальная роль «Все пользователи» клонировать нельзя")
    base = f"{src.name} (копия)"
    name = base
    n = 2
    while db.execute(select(models.Role).where(models.Role.name == name)).scalar_one_or_none():
        name = f"{base} {n}"
        n += 1
    clone = models.Role(name=name)
    for p in src.permissions:
        clone.permissions.append(models.RolePermission(permission=p.permission))
    db.add(clone)
    db.commit()
    return to_out(clone)
