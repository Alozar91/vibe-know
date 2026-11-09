# Use-case: назначение роли пользователю (FR-007, US-003 шаг 2) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import get_role_or_404, get_user_or_404, require_super
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.permissions.cache import commit_rights


def assign_role(db: Session, is_super: bool, user_id: str, role_id: str, actor=None) -> None:
    """Идемпотентно: повторное назначение не создаёт дубликат (FR-010)."""
    require_super(is_super)
    target = get_user_or_404(db, user_id)
    role = get_role_or_404(db, role_id)
    link = db.execute(
        select(models.UserRole).where(
            models.UserRole.user_id == target.id, models.UserRole.role_id == role.id
        )
    ).scalar_one_or_none()
    if link is None:
        db.add(models.UserRole(user_id=target.id, role_id=role.id))
        # US-049 ш.1 (FR-140, LLD §11 user.role_assign)
        if actor is not None:
            audit_log(db, actor, "user.role_assign", "user", target.id,
                      details={"role": role.name})
        commit_rights(db)
