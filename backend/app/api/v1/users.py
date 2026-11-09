# Users: список/карточка, деактивация (LLD §12.3: GET /users, GET /users/{id}, DELETE /users/{id}).
# Создание — только Keycloak (FR-006): POST нет; DELETE — soft-деактивация (FR-011).
# Деактивация в системе — вспомогательная (обычно в Keycloak, US-004); свёрка — этап 10.
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db import models
from app.db.engine import get_db
from fastapi import Depends

router = APIRouter(tags=["users"])


def _require_super(user: CurrentUserDep) -> None:
    """FR-104: операции управления пользователями — только СА."""
    if not user.is_super:
        raise HTTPException(status_code=403, detail="Доступ только для системного администратора")


def _get_user(db: Session, user_id: str) -> models.User | None:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None
    return db.execute(select(models.User).where(models.User.id == uid)).scalar_one_or_none()


class UserOut(BaseModel):
    id: str
    display_name: str
    email_cache: str | None
    is_deactivated: bool
    is_service: bool
    roles: list[str]

    model_config = {"from_attributes": True}


def _to_out(u: models.User) -> UserOut:
    return UserOut(
        id=str(u.id),
        display_name=u.display_name,
        email_cache=u.email_cache,
        is_deactivated=u.is_deactivated,
        is_service=u.is_service,
        roles=[ur.role.name for ur in u.roles],
    )


@router.get("/users")
async def list_users(
    user: CurrentUserDep,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
) -> dict:
    """Список учётных записей (FR-005; пагинация FR-131: page/per_page, макс. 200)."""
    _require_super(user)
    per_page = min(per_page, 200)
    total = db.execute(select(func.count(models.User.id))).scalar_one()
    rows = db.execute(
        select(models.User)
        .order_by(models.User.created_at)
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).scalars().all()
    return {"items": [_to_out(u).model_dump() for u in rows], "total": total, "page": page, "per_page": per_page}


@router.get("/users/{user_id}")
async def get_user(user: CurrentUserDep, user_id: str, db: Session = Depends(get_db)) -> dict:
    """Карточка пользователя (FR-006)."""
    _require_super(user)
    u = _get_user(db, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return _to_out(u).model_dump()


@router.delete("/users/{user_id}")
async def deactivate_user(user: CurrentUserDep, user_id: str, db: Session = Depends(get_db)) -> dict:
    """Деактивация (soft, FR-006/FR-011): обратима активацией в Keycloak/сверкой (этап 10)."""
    _require_super(user)
    u = _get_user(db, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if u.id == user.user_id:
        raise HTTPException(status_code=409, detail="Нельзя деактивировать собственную учётную запись")
    u.is_deactivated = True
    return {"id": str(u.id), "is_deactivated": True}
