# Use-case: создание шаблона роли (FR-008, US-043) — только СА.
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import require_super, validate_permissions
from app.use_cases.errors import name_conflict
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.roles.dto import to_out
from app.use_cases.permissions.cache import commit_rights


def create_role(db: Session, is_super: bool, name: str, permissions: list[str], actor=None) -> dict:
    require_super(is_super)
    _ensure_name_free(db, name)
    role = models.Role(name=name)
    for code in validate_permissions(permissions):
        role.permissions.append(models.RolePermission(permission=code))
    db.add(role)
    db.flush()
    # US-049 ш.1 (FR-140, LLD §11 role.create)
    if actor is not None:
        audit_log(db, actor, "role.create", "role", role.id,
                  details={"name": role.name, "permissions": list(permissions)})
    commit_rights(db)
    return to_out(role)


def _ensure_name_free(db: Session, name: str) -> None:
    from sqlalchemy import select

    if db.execute(select(models.Role).where(models.Role.name == name)).scalar_one_or_none():
        raise name_conflict("Роль с таким названием уже существует")
