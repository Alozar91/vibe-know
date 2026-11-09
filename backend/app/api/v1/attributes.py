# Attributes — транспорт (LLD §12.3). Логика: use_cases/attributes/*.
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases.attributes.create_attribute import create_attribute
from app.use_cases.attributes.delete_attribute import delete_attribute
from app.use_cases.attributes.list_attributes import list_attributes
from app.use_cases.attributes.update_attribute import update_attribute

router = APIRouter(tags=["attributes"])


class AttributeIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    value_type: str
    is_multivalue: bool = False
    is_required: bool = False
    display_order: int = 0
    dictionary_id: str | None = None


class AttributePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_required: bool | None = None
    display_order: int | None = None


@router.get("/attributes")
async def list_attributes_ep(user: CurrentUserDep, db: Session = Depends(get_db)) -> list[dict]:
    """Глобальный пул атрибутов (FR-044)."""
    return list_attributes(db)


@router.post("/attributes", status_code=201)
async def create_attribute_ep(user: CurrentUserDep, body: AttributeIn, db: Session = Depends(get_db)) -> dict:
    """Создание атрибута (FR-044, US-030 шаг 1) — СА."""
    return create_attribute(
        db, user.is_super, body.name, body.value_type,
        is_multivalue=body.is_multivalue, is_required=body.is_required,
        display_order=body.display_order, dictionary_id=body.dictionary_id,
    )


@router.patch("/attributes/{attribute_id}")
async def update_attribute_ep(
    user: CurrentUserDep, attribute_id: str, body: AttributePatch, db: Session = Depends(get_db)
) -> dict:
    """Правка (FR-045: value_type/is_multivalue неизменяемы) — СА."""
    return update_attribute(
        db, user.is_super, attribute_id,
        name=body.name, is_required=body.is_required, display_order=body.display_order,
    )


@router.delete("/attributes/{attribute_id}", status_code=204)
async def delete_attribute_ep(user: CurrentUserDep, attribute_id: str, db: Session = Depends(get_db)) -> None:
    """Удаление (FR-050: запрет при использовании) — СА."""
    delete_attribute(db, user.is_super, attribute_id)
