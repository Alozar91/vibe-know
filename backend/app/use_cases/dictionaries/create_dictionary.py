# Use-case: создание справочника (FR-047, US-033 шаг 1) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import require_super
from app.use_cases.dictionaries.dto import to_out
from app.use_cases.errors import DomainError, name_conflict
from app.use_cases.lifecycle.audit import audit_log


def create_dictionary(db: Session, is_super: bool, name: str, actor=None) -> dict:
    require_super(is_super)
    if not name or not name.strip():
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Название справочника обязательно")
    if db.execute(select(models.Dictionary).where(models.Dictionary.name == name.strip())).scalar_one_or_none():
        raise name_conflict("Справочник с таким названием уже существует")
    d = models.Dictionary(name=name.strip())
    db.add(d)
    db.flush()
    # US-049 ш.1 (FR-140, LLD §11 dictionary.create)
    if actor is not None:
        audit_log(db, actor, "dictionary.create", "dictionary", d.id,
                  details={"name": d.name})
    db.commit()
    return to_out(d)
