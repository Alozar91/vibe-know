# Use-case: клонирование шаблона роли (FR-105, US-003 шаг 2) — только СА.
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import get_role_or_404, require_super
from app.use_cases.errors import domain_rule_violation
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.roles.constants import VIRTUAL_ALL_USERS_NAME
from app.use_cases.roles.dto import to_out
from app.use_cases.permissions.cache import commit_rights


def clone_role(db: Session, is_super: bool, role_id: str, actor=None) -> dict:
    """Клон = копия набора прав; имя уникализируется суффиксом.

    Гонка двух одновременных клонов (между SELECT и INSERT) ловится
    IntegrityError по UNIQUE name: откат и пересчёт суффикса.
    """
    require_super(is_super)
    src = get_role_or_404(db, role_id)
    if src.is_virtual_all_users:
        raise domain_rule_violation(
            409, f"Виртуальная роль «{VIRTUAL_ALL_USERS_NAME}» клонировать нельзя"
        )
    for attempt in range(3):
        name = _next_free_name(db, src.name)
        clone = models.Role(name=name)
        for p in src.permissions:
            clone.permissions.append(models.RolePermission(permission=p.permission))
        db.add(clone)
        db.flush()
        # US-049 ш.1 (FR-140, LLD §11 role.clone): до commit_rights
        if actor is not None:
            audit_log(db, actor, "role.clone", "role", clone.id,
                      details={"source": src.name, "name": clone.name})
        try:
            commit_rights(db)
            return to_out(clone)
        except IntegrityError:
            db.rollback()
    # Не сумели за 3 попыток (экстремальная гонка) — честный конфликт
    raise domain_rule_violation(409, "Не удалось уникализировать имя клона, повторите запрос")


def _next_free_name(db: Session, src_name: str) -> str:
    base = f"{src_name} (копия)"
    name = base
    n = 2
    while db.execute(select(models.Role).where(models.Role.name == name)).scalar_one_or_none():
        name = f"{base} {n}"
        n += 1
    return name
