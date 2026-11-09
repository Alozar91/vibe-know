# Назначение ролей (LLD §12.3: PUT/DELETE /users/{id}/roles/{role_id}, FR-007, FR-010).
import uuid

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db import models
from app.db.engine import get_db

router = APIRouter(tags=["roles"])


def _require_super(user: CurrentUserDep) -> None:
    if not user.is_super:
        raise HTTPException(status_code=403, detail="Доступ только для системного администратора")


def _get_user(db: Session, user_id: str) -> models.User | None:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None
    return db.execute(select(models.User).where(models.User.id == uid)).scalar_one_or_none()


def _get_role(db: Session, role_id: str) -> models.Role | None:
    try:
        rid = uuid.UUID(role_id)
    except ValueError:
        return None
    return db.execute(select(models.Role).where(models.Role.id == rid)).scalar_one_or_none()


@router.put("/users/{user_id}/roles/{role_id}", status_code=204)
async def assign_role(user: CurrentUserDep, user_id: str, role_id: str, db: Session = Depends(get_db)) -> None:
    """Назначение роли в системе — служебный раздел СА (FR-007, US-003 шаг 2)."""
    _require_super(user)
    target = _get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    role = _get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Роль не найдена")
    exists = db.execute(
        select(models.UserRole).where(
            models.UserRole.user_id == target.id, models.UserRole.role_id == role.id
        )
    ).first()
    if not exists:
        db.add(models.UserRole(user_id=target.id, role_id=role.id))
        db.commit()
    return None


@router.delete("/users/{user_id}/roles/{role_id}", status_code=204)
async def revoke_role(user: CurrentUserDep, user_id: str, role_id: str, db: Session = Depends(get_db)) -> None:
    """Снятие роли (FR-007, FR-010)."""
    _require_super(user)
    try:
        uid, rid = uuid.UUID(user_id), uuid.UUID(role_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Роль не назначена")
    link = db.execute(
        select(models.UserRole).where(
            models.UserRole.user_id == uid, models.UserRole.role_id == rid
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Роль не назначена")
    db.delete(link)
    db.commit()
    return None
