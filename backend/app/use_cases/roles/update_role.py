# Use-case: правка шаблона роли (FR-008, US-043 шаг 2) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import get_role_or_404, require_super, validate_permissions
from app.use_cases.errors import domain_rule_violation, name_conflict
from app.use_cases.roles.constants import VIRTUAL_ALL_USERS_NAME
from app.use_cases.roles.dto import to_out


def update_role(
    db: Session, is_super: bool, role_id: str, name: str | None, permissions: list[str] | None
) -> dict:
    """Правка состава/названия; на уже созданные снапшоты не влияет (FR-100) — этап 4."""
    require_super(is_super)
    role = get_role_or_404(db, role_id)
    if role.is_virtual_all_users and (permissions is not None or name is not None):
        raise domain_rule_violation(
            409, f"Виртуальная роль «{VIRTUAL_ALL_USERS_NAME}» не редактируется"
        )
    if name is not None and name != role.name:
        if db.execute(
            select(models.Role).where(
                models.Role.name == name, models.Role.id != role.id
            )
        ).scalar_one_or_none():
            raise name_conflict("Роль с таким названием уже существует")
        role.name = name
    if permissions is not None:
        role.permissions.clear()
        for code in validate_permissions(permissions):
            role.permissions.append(models.RolePermission(permission=code))
    db.commit()
    return to_out(role)
