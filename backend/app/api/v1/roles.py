# Роли-шаблоны: CRUD + клонирование (LLD §12.3, FR-008, FR-105).
# Шаблоны редактирует только СА (US-043); клонирование = копия набора прав (FR-105).
import uuid

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db import models
from app.db.engine import get_db

router = APIRouter(tags=["roles"])


def _get_role(db: Session, role_id: str) -> models.Role | None:
    try:
        rid = uuid.UUID(role_id)
    except ValueError:
        return None
    return db.execute(select(models.Role).where(models.Role.id == rid)).scalar_one_or_none()


def _require_super(user: CurrentUserDep) -> None:
    if not user.is_super:
        raise HTTPException(status_code=403, detail="Доступ только для системного администратора")


class RoleOut(BaseModel):
    id: str
    name: str
    is_virtual_all_users: bool
    permissions: list[str]


def _to_out(r: models.Role) -> RoleOut:
    perms = sorted(
        p.permission.value if hasattr(p.permission, "value") else str(p.permission)
        for p in r.permissions
    )
    return RoleOut(
        id=str(r.id),
        name=r.name,
        is_virtual_all_users=r.is_virtual_all_users,
        permissions=perms,
    )


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    permissions: list[str] = Field(default_factory=list)


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    permissions: list[str] | None = None


@router.get("/roles")
async def list_roles(user: CurrentUserDep, db: Session = Depends(get_db)) -> list[dict]:
    """Шаблоны ролей (FR-008): базовые + клоны + виртуальная «Все пользователи»."""
    rows = db.execute(select(models.Role).order_by(models.Role.created_at)).scalars().all()
    return [_to_out(r).model_dump() for r in rows]


@router.post("/roles", status_code=201)
async def create_role(user: CurrentUserDep, body: RoleIn, db: Session = Depends(get_db)) -> dict:
    """Создание шаблона (FR-008; правки — US-043)."""
    _require_super(user)
    exists = db.execute(select(models.Role).where(models.Role.name == body.name)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Роль с таким названием уже существует")
    role = models.Role(name=body.name)
    for p in set(body.permissions):
        try:
            role.permissions.append(models.RolePermission(permission=models.PermissionCode(p)))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Неизвестное право: {p}")
    db.add(role)
    db.commit()
    return _to_out(role).model_dump()


@router.patch("/roles/{role_id}")
async def update_role(user: CurrentUserDep, role_id: str, body: RolePatch, db: Session = Depends(get_db)) -> dict:
    """Правка состава шаблона (FR-008, US-043 шаг 2). Не влияет на существующие снапшоты (FR-100)."""
    _require_super(user)
    role = _get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Роль не найдена")
    if role.is_virtual_all_users and body.permissions is not None:
        raise HTTPException(status_code=409, detail="Виртуальная роль «Все пользователи» не имеет состава прав")
    if body.name is not None and body.name != role.name:
        dup = db.execute(select(models.Role).where(models.Role.name == body.name)).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail="Роль с таким названием уже существует")
        role.name = body.name
    if body.permissions is not None:
        role.permissions.clear()
        for p in set(body.permissions):
            try:
                role.permissions.append(models.RolePermission(permission=models.PermissionCode(p)))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Неизвестное право: {p}")
    db.commit()
    return _to_out(role).model_dump()


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(user: CurrentUserDep, role_id: str, db: Session = Depends(get_db)) -> None:
    """Удаление шаблона (FR-008)."""
    _require_super(user)
    role = _get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Роль не найдена")
    db.delete(role)
    db.commit()


@router.post("/roles/{role_id}/clone", status_code=201)
async def clone_role(user: CurrentUserDep, role_id: str, db: Session = Depends(get_db)) -> dict:
    """Клонирование: копия набора прав шаблона (FR-105, US-003 шаг 2)."""
    _require_super(user)
    src = _get_role(db, role_id)
    if src is None:
        raise HTTPException(status_code=404, detail="Роль не найдена")
    if src.is_virtual_all_users:
        raise HTTPException(status_code=409, detail="Виртуальная роль «Все пользователи» клонировать нельзя")
    base = f"{src.name} (копия)"
    name = base
    n = 2
    while db.execute(select(models.Role).where(models.Role.name == name)).scalar_one_or_none():
        name = f"{base} {n}"
        n += 1
    clone = models.Role(name=name)
    for p in src.permissions:
        clone.permissions.append(models.RolePermission(permission=p.permission))
    db.add(clone)
    db.commit()
    return _to_out(clone).model_dump()
