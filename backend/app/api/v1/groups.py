# Groups — транспорт (LLD §12.3). Логика: use_cases/groups/*.
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases.groups.create_group import create_group
from app.use_cases.groups.delete_group import delete_group
from app.use_cases.groups.list_groups import list_groups
from app.use_cases.groups.rename_group import rename_group

router = APIRouter(tags=["groups"])


class GroupIn(BaseModel):
    # Верхняя граница не в Pydantic: NAME_TOO_LONG (LLD §12.2) должен отдавать use-case
    name: str = Field(min_length=1)
    parent_id: str | None = None


class GroupPatch(BaseModel):
    name: str = Field(min_length=1)


@router.get("/groups")
async def list_groups_ep(
    user: CurrentUserDep, db: Session = Depends(get_db)
) -> list[dict]:
    """Дерево групп (FR-015); удалённые — этап 10 (US-050)."""
    return list_groups(db)


@router.get("/groups/deleted")
async def deleted_groups(user: CurrentUserDep, db: Session = Depends(get_db)) -> list[dict]:
    """Удалённые группы — служебный раздел (FR-021, US-050; просмотр — СА)."""
    from app.use_cases.common import require_super

    require_super(user.is_super)
    return list_groups(db, only_deleted=True)


@router.get("/groups/{group_id}")
async def get_group_ep(user: CurrentUserDep, group_id: str, db: Session = Depends(get_db)) -> dict:
    """Карточка группы (FR-016)."""
    from app.use_cases.common import get_group_or_404
    from app.use_cases.groups.dto import to_out

    g = get_group_or_404(db, group_id, allow_deleted=user.is_super)
    return to_out(g)


@router.post("/groups", status_code=201)
async def create_group_ep(user: CurrentUserDep, body: GroupIn, db: Session = Depends(get_db)) -> dict:
    """Создание группы (FR-015/016, US-052 шаг 1) — СА."""
    from app.use_cases.groups.create_group import create_group as uc

    return uc(db, user.is_super, body.name, body.parent_id, actor=user)


@router.patch("/groups/{group_id}")
async def rename_group_ep(
    user: CurrentUserDep, group_id: str, body: GroupPatch, db: Session = Depends(get_db)
) -> dict:
    """Переименование (FR-015, US-052 шаг 3) — СА."""
    from app.use_cases.groups.rename_group import rename_group as uc

    return uc(db, user.is_super, group_id, body.name, actor=user)


@router.delete("/groups/{group_id}")
async def delete_group_ep(
    user: CurrentUserDep, group_id: str, confirm_rights: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    """Удаление: физ./soft решает система; права — с подтверждением (FR-018–020, US-052)."""
    from app.use_cases.groups.delete_group import delete_group as uc

    return uc(db, user.is_super, group_id, confirm_rights=confirm_rights, actor=user)
