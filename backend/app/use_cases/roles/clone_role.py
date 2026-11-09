# Use-case: клонирование шаблона роли (FR-105, US-003 шаг 2) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import get_role_or_404, require_super
from app.use_cases.errors import domain_rule_violation
from app.use_cases.roles.constants import VIRTUAL_ALL_USERS_NAME
from app.use_cases.roles.dto import to_out


def clone_role(db: Session, is_super: bool, role_id: str) -> dict:
    """Клон = копия набора прав; имя уникализируется суффиксом."""
    require_super(is_super)
    src = get_role_or_404(db, role_id)
    if src.is_virtual_all_users:
        raise domain_rule_violation(
            409, f"Виртуальная роль «{VIRTUAL_ALL_USERS_NAME}» клонировать нельзя"
        )
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
