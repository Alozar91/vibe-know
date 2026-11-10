# Use-case: список учётных записей (FR-005, FR-131) — только СА.
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import require_super
from app.use_cases.users.dto import UserOut, to_out


@dataclass
class UsersPage:
    """Конверт пагинации FR-131: max 200 на страницу (LLD §12.1)."""

    items: list[UserOut]
    total: int
    page: int
    per_page: int


def list_users(db: Session, is_super: bool, page: int = 1, per_page: int = 50) -> UsersPage:
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
    return UsersPage(items=[to_out(u) for u in rows], total=total, page=page, per_page=per_page)
