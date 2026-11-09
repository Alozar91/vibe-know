# Сценарии пользователей: список, карточка, деактивация (LLD §12.3, FR-005–011).
# Создание — только Keycloak (FR-006): POST нет; DELETE — soft-деактивация (FR-011).
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import get_user_or_404, require_super
from app.use_cases.errors import self_deactivation_forbidden


@dataclass
class UserOut:
    """DTO карточки пользователя (FR-151: минимум ПДн)."""

    id: str
    display_name: str
    email_cache: str | None
    is_deactivated: bool
    is_service: bool
    roles: list[str] = field(default_factory=list)


def to_out(u: models.User) -> UserOut:
    return UserOut(
        id=str(u.id),
        display_name=u.display_name,
        email_cache=u.email_cache,
        is_deactivated=u.is_deactivated,
        is_service=u.is_service,
        roles=[ur.role.name for ur in u.roles],
    )


@dataclass
class Page:
    """Пагинация FR-131: конверт {items,total,page,per_page}, максимум 200."""

    items: list
    total: int
    page: int
    per_page: int


def list_users(db: Session, is_super: bool, page: int = 1, per_page: int = 50) -> Page:
    """Список учётных записей (FR-005) — только СА."""
    require_super(is_super)
    per_page = min(max(per_page, 1), 200)
    page = max(page, 1)
    total = db.execute(select(func.count(models.User.id))).scalar_one()
    rows = (
        db.execute(
            select(models.User)
            .order_by(models.User.created_at)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        .scalars()
        .all()
    )
    return Page(items=[to_out(u) for u in rows], total=total, page=page, per_page=per_page)


def get_user(db: Session, is_super: bool, user_id: str) -> UserOut:
    """Карточка пользователя (FR-006) — только СА."""
    require_super(is_super)
    return to_out(get_user_or_404(db, user_id))


def deactivate_user(db: Session, actor: models.User, is_super: bool, user_id: str) -> UserOut:
    """Деактивация (soft, FR-006/FR-011) — только СА; самодеактивация запрещена.

    Обратима активацией в Keycloak/сверкой (этап 10, US-004).
    """
    require_super(is_super)
    u = get_user_or_404(db, user_id)
    if u.id == actor.id:
        raise self_deactivation_forbidden()
    u.is_deactivated = True
    db.commit()
    return to_out(u)
