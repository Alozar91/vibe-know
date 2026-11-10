# Types — транспорт (LLD §12.3). Логика: use_cases/types/*.
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases.types.bind_attribute import bind_attribute
from app.use_cases.types.create_type import create_type
from app.use_cases.types.delete_type import delete_type
from app.use_cases.types.list_types import list_types
from app.use_cases.types.rename_type import rename_type
from app.use_cases.types.unbind_attribute import unbind_attribute

router = APIRouter(tags=["types"])


class TypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    attribute_ids: list[str] = Field(default_factory=list)


class TypePatch(BaseModel):
    name: str = Field(min_length=1, max_length=255)


@router.get("/types")
def list_types_ep(user: CurrentUserDep, db: Session = Depends(get_db)) -> list[dict]:
    """Типы материалов с атрибутами (FR-043)."""
    return list_types(db)


@router.post("/types", status_code=201)
def create_type_ep(user: CurrentUserDep, body: TypeIn, db: Session = Depends(get_db)) -> dict:
    """Создание типа (FR-043, US-030 шаг 2) — СА."""
    from app.use_cases.types.create_type import create_type as uc

    return uc(db, user.is_super, body.name, body.attribute_ids, actor=user)


@router.patch("/types/{type_id}")
def rename_type_ep(
    user: CurrentUserDep, type_id: str, body: TypePatch, db: Session = Depends(get_db)
) -> dict:
    """Переименование типа (FR-043) — СА."""
    from app.use_cases.types.rename_type import rename_type as uc

    return uc(db, user.is_super, type_id, body.name, actor=user)


@router.delete("/types/{type_id}", status_code=204)
def delete_type_ep(user: CurrentUserDep, type_id: str, db: Session = Depends(get_db)) -> None:
    """Удаление типа (FR-050) — СА; запрет при использовании."""
    from app.use_cases.types.delete_type import delete_type as uc

    uc(db, user.is_super, type_id, actor=user)


@router.post("/types/{type_id}/attributes/{attribute_id}", status_code=204)
def bind_attribute_ep(
    user: CurrentUserDep, type_id: str, attribute_id: str, db: Session = Depends(get_db)
) -> None:
    """Привязка атрибута (FR-044; лимит 50) — СА."""
    bind_attribute(db, user.is_super, type_id, attribute_id)


@router.delete("/types/{type_id}/attributes/{attribute_id}", status_code=204)
def unbind_attribute_ep(
    user: CurrentUserDep, type_id: str, attribute_id: str, db: Session = Depends(get_db)
) -> None:
    """Исключение атрибута (FR-051: значения остаются) — СА."""
    unbind_attribute(db, user.is_super, type_id, attribute_id)
