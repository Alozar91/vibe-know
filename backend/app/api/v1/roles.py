# Roles — транспорт (LLD §12.3). Логика: use_cases/roles/* (сценарий на файл).
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases.roles.assign_role import assign_role
from app.use_cases.roles.clone_role import clone_role
from app.use_cases.roles.create_role import create_role
from app.use_cases.roles.delete_role import delete_role
from app.use_cases.roles.list_roles import list_roles
from app.use_cases.roles.revoke_role import revoke_role
from app.use_cases.roles.update_role import update_role

router = APIRouter(tags=["roles"])


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    permissions: list[str] = Field(default_factory=list)


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    permissions: list[str] | None = None


@router.get("/roles")
def list_roles_ep(user: CurrentUserDep, db: Session = Depends(get_db)) -> list[dict]:
    """Шаблоны ролей (FR-008)."""
    return list_roles(db)


@router.post("/roles", status_code=201)
def create_role_ep(user: CurrentUserDep, body: RoleIn, db: Session = Depends(get_db)) -> dict:
    """Создание шаблона (FR-008, US-043) — СА."""
    from app.use_cases.roles.create_role import create_role as uc

    return uc(db, user.is_super, body.name, body.permissions, actor=user)


@router.patch("/roles/{role_id}")
def update_role_ep(
    user: CurrentUserDep, role_id: str, body: RolePatch, db: Session = Depends(get_db)
) -> dict:
    """Правка шаблона (FR-008, US-043 шаг 2) — СА; снапшоты не затрагивает (FR-100)."""
    from app.use_cases.roles.update_role import update_role as uc

    return uc(db, user.is_super, role_id, body.name, body.permissions, actor=user)


@router.delete("/roles/{role_id}", status_code=204)
def delete_role_ep(user: CurrentUserDep, role_id: str, db: Session = Depends(get_db)) -> None:
    """Удаление шаблона (FR-008) — СА."""
    from app.use_cases.roles.delete_role import delete_role as uc

    uc(db, user.is_super, role_id, actor=user)


@router.post("/roles/{role_id}/clone", status_code=201)
def clone_role_ep(user: CurrentUserDep, role_id: str, db: Session = Depends(get_db)) -> dict:
    """Клонирование: копия набора прав (FR-105, US-003 шаг 2) — СА."""
    from app.use_cases.roles.clone_role import clone_role as uc

    return uc(db, user.is_super, role_id, actor=user)
