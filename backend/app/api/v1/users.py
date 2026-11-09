# Users — транспорт (LLD §12.3). Логика: use_cases.users.
from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases import users as users_uc

router = APIRouter(tags=["users"])


@router.get("/users")
async def list_users(
    user: CurrentUserDep,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
) -> dict:
    """Список учётных записей (FR-005; пагинация FR-131) — СА."""
    p = users_uc.list_users(db, user.is_super, page=page, per_page=per_page)
    return {
        "items": [asdict(u) for u in p.items],
        "total": p.total,
        "page": p.page,
        "per_page": p.per_page,
    }


@router.get("/users/{user_id}")
async def get_user(user: CurrentUserDep, user_id: str, db: Session = Depends(get_db)) -> dict:
    """Карточка пользователя (FR-006) — СА."""
    return asdict(users_uc.get_user(db, user.is_super, user_id))


@router.delete("/users/{user_id}")
async def deactivate_user(user: CurrentUserDep, user_id: str, db: Session = Depends(get_db)) -> dict:
    """Деактивация (soft, FR-006/FR-011) — СА."""
    u = users_uc.deactivate_user(db, user.db_user, user.is_super, user_id)
    return {"id": u.id, "is_deactivated": u.is_deactivated}
