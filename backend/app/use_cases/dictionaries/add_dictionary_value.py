# Use-case: добавление значения справочника (FR-047, US-033 шаг 1) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, name_conflict, not_found


def add_dictionary_value(db: Session, is_super: bool, dictionary_id: str, value: str) -> dict:
    require_super(is_super)
    d = db.execute(
        select(models.Dictionary).where(models.Dictionary.id == parse_uuid(dictionary_id))
    ).scalar_one_or_none()
    if d is None:
        raise not_found("Справочник не найден")
    if not value or not value.strip():
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Значение обязательно")
    dup = db.execute(
        select(models.DictionaryValue).where(
            models.DictionaryValue.dictionary_id == d.id,
            models.DictionaryValue.value == value.strip(),
        )
    ).scalar_one_or_none()
    if dup:
        raise name_conflict("Такое значение уже есть в справочнике")
    v = models.DictionaryValue(dictionary_id=d.id, value=value.strip())
    db.add(v)
    db.commit()
    return {"id": str(v.id), "value": v.value}
