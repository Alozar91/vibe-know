# Use-case: деактивация учётной записи (FR-006, FR-011; US-004) — только СА.
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import get_user_or_404, require_super
from app.use_cases.errors import self_deactivation_forbidden
from app.use_cases.users.dto import UserOut, to_out
from app.use_cases.permissions.cache import commit_rights


def deactivate_user(
    db: Session, actor: models.User, is_super: bool, user_id: str
) -> UserOut:
    """Soft-деактивация; самодеактивация запрещена (деактивирует другой СА, US-004).

    Обратима активацией в Keycloak/сверкой (этап 10).
    """
    require_super(is_super)
    u = get_user_or_404(db, user_id)
    if u.id == actor.id:
        raise self_deactivation_forbidden()
    u.is_deactivated = True
    commit_rights(db)
    return to_out(u)
