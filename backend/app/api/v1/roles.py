# Roles — транспорт (LLD §12.3). Логика: use_cases.roles.
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases import roles as roles_uc

router = APIRouter(tags=["roles"])


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    permissions: list[str] = Field(default_factory=list)


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    permissions: list[str] | None = None


@router.get("/roles")
async def list_roles(user: CurrentUserDep, db: Session = Depends(get_db)) -> list[dict]:
    """Шаблоны ролей (FR-008)."""
    return roles_uc.list_roles(db)


@router.post("/roles", status_code=201)
async def create_role(user: CurrentUserDep, body: RoleIn, db: Session = Depends(get_db)) -> dict:
    """Создание шаблона (FR-008, US-043) — СА."""
    return roles_uc.create_role(db, user.is_super, body.name, body.permissions)


@router.patch("/roles/{role_id}")
async def update_role(
    user: CurrentUserDep, role_id: str, body: RolePatch, db: Session = Depends(get_db)
) -> dict:
    """Правка шаблона (FR-008, US-043 шаг 2) — СА; снапшоты не затрагивает (FR-100)."""
    return roles_uc.update_role(db, user.is_super, role_id, body.name, body.permissions)


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(user: CurrentUserDep, role_id: str, db: Session = Depends(get_db)) -> None:
    """Удаление шаблона (FR-008) — СА."""
    roles_uc.delete_role(db, user.is_super, role_id)


@router.post("/roles/{role_id}/clone", status_code=201)
async def clone_role(user: CurrentUserDep, role_id: str, db: Session = Depends(get_db)) -> dict:
    """Клонирование: копия набора прав (FR-105, US-003 шаг 2) — СА."""
    return roles_uc.clone_role(db, user.is_super, role_id)
