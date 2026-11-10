# Use-case: флаг суперпользователя сессии (FR-104, LLD §3.2).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.roles.constants import SUPERUSER_ROLE_NAME


def is_super(db: Session, user: models.User) -> bool:
    """Принадлежность шаблону «Системный администратор» — обход прав (FR-104)."""
    admin_role = db.execute(
        select(models.Role).where(models.Role.name == SUPERUSER_ROLE_NAME)
    ).scalar_one_or_none()
    if admin_role is None:
        return False
    link = db.execute(
        select(models.UserRole).where(
            models.UserRole.user_id == user.id, models.UserRole.role_id == admin_role.id
        )
    ).first()
    return link is not None
