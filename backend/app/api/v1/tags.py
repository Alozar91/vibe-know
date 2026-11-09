# Tags — транспорт (LLD §12.3). Логика: use_cases/tags/*.
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases.tags.create_tag import create_tag
from app.use_cases.tags.delete_tag import delete_tag
from app.use_cases.tags.list_tags import list_tags
from app.use_cases.tags.merge_tag import merge_tag

router = APIRouter(tags=["tags"])


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TagMergeIn(BaseModel):
    target_id: str


@router.get("/tags")
async def list_tags_ep(
    user: CurrentUserDep, q: str | None = None, db: Session = Depends(get_db)
) -> list[dict]:
    """Словарь тегов (FR-052); q — автодополнение (US-031 шаг 4)."""
    return list_tags(db, q)


@router.post("/tags", status_code=201)
async def create_tag_ep(user: CurrentUserDep, body: TagIn, db: Session = Depends(get_db)) -> dict:
    """Создание тега (US-033 шаг 2) — СА."""
    from app.use_cases.tags.create_tag import create_tag as uc

    return uc(db, user.is_super, body.name, actor=user)


@router.post("/tags/{tag_id}:merge")
async def merge_tag_ep(
    user: CurrentUserDep, tag_id: str, body: TagMergeIn, db: Session = Depends(get_db)
) -> dict:
    """Слияние тегов (FR-053, US-033 шаг 3) — СА."""
    from app.use_cases.tags.merge_tag import merge_tag as uc

    return uc(db, user.is_super, tag_id, body.target_id, actor=user)


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag_ep(user: CurrentUserDep, tag_id: str, db: Session = Depends(get_db)) -> None:
    """Удаление тега (FR-054: запрет при использовании) — СА."""
    from app.use_cases.tags.delete_tag import delete_tag as uc

    uc(db, user.is_super, tag_id, actor=user)
