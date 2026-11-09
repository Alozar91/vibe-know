# Dictionaries — транспорт (LLD §12.3). Логика: use_cases/dictionaries/*.
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases.dictionaries.add_dictionary_value import add_dictionary_value
from app.use_cases.dictionaries.create_dictionary import create_dictionary
from app.use_cases.dictionaries.delete_dictionary_value import delete_dictionary_value
from app.use_cases.dictionaries.list_dictionaries import list_dictionaries
from app.use_cases.dictionaries.rename_dictionary import rename_dictionary

router = APIRouter(tags=["dictionaries"])


class DictionaryIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class DictionaryValueIn(BaseModel):
    value: str = Field(min_length=1)


@router.get("/dictionaries")
async def list_dictionaries_ep(user: CurrentUserDep, db: Session = Depends(get_db)) -> list[dict]:
    """Справочники со значениями (FR-047)."""
    return list_dictionaries(db)


@router.post("/dictionaries", status_code=201)
async def create_dictionary_ep(user: CurrentUserDep, body: DictionaryIn, db: Session = Depends(get_db)) -> dict:
    """Создание справочника (US-033 шаг 1) — СА."""
    from app.use_cases.dictionaries.create_dictionary import create_dictionary as uc

    return uc(db, user.is_super, body.name, actor=user)


@router.patch("/dictionaries/{dictionary_id}")
async def rename_dictionary_ep(
    user: CurrentUserDep, dictionary_id: str, body: DictionaryIn, db: Session = Depends(get_db)
) -> dict:
    """Переименование справочника — СА."""
    from app.use_cases.dictionaries.rename_dictionary import rename_dictionary as uc

    return uc(db, user.is_super, dictionary_id, body.name, actor=user)


@router.post("/dictionaries/{dictionary_id}/values", status_code=201)
async def add_value_ep(
    user: CurrentUserDep, dictionary_id: str, body: DictionaryValueIn, db: Session = Depends(get_db)
) -> dict:
    """Добавление значения (US-033 шаг 1) — СА; свободный ввод пользователями запрещён (FR-047)."""
    from app.use_cases.dictionaries.add_dictionary_value import add_dictionary_value as uc

    return uc(db, user.is_super, dictionary_id, body.value, actor=user)


@router.delete("/dictionaries/{dictionary_id}/values/{value_id}", status_code=204)
async def delete_value_ep(
    user: CurrentUserDep, dictionary_id: str, value_id: str, db: Session = Depends(get_db)
) -> None:
    """Удаление значения (FR-047: запрет при использовании) — СА."""
    from app.use_cases.dictionaries.delete_dictionary_value import delete_dictionary_value as uc

    uc(db, user.is_super, value_id, actor=user)
