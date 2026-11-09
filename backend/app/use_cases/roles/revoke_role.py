# Use-case: снятие роли (FR-007, FR-010) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import get_role_or_404, get_user_or_404, require_super
from app.use_cases.errors import not_found


def revoke_role(db: Session, is_super: bool, user_id: str, role_id: str) -> None:
    require_super(is_super)
    target = get_user_or_404(db, user_id)
    role = get_role_or_404(db, role_id)
    link = db.execute(
        select(models.UserRole).where(
            models.UserRole.user_id == target.id, models.UserRole.role_id == role.id
        )
    ).scalar_one_or_none()
    if link is None:
        raise not_found("Роль не назначена")
    db.delete(link)
    db.commit()
