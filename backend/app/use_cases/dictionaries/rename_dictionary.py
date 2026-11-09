# Use-case: переименование справочника (FR-047) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.dictionaries.dto import to_out
from app.use_cases.errors import DomainError, name_conflict, not_found
from app.use_cases.lifecycle.audit import audit_log


def rename_dictionary(db: Session, is_super: bool, dictionary_id: str, name: str, actor=None) -> dict:
    require_super(is_super)
    d = db.execute(
        select(models.Dictionary).where(models.Dictionary.id == parse_uuid(dictionary_id))
    ).scalar_one_or_none()
    if d is None:
        raise not_found("Справочник не найден")
    if not name or not name.strip():
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Название справочника обязательно")
    dup = db.execute(
        select(models.Dictionary).where(
            models.Dictionary.name == name.strip(), models.Dictionary.id != d.id
        )
    ).scalar_one_or_none()
    if dup:
        raise name_conflict("Справочник с таким названием уже существует")
    old_name = d.name
    d.name = name.strip()
    # US-049 ш.1 (FR-140, LLD §11 dictionary.rename)
    if actor is not None:
        audit_log(db, actor, "dictionary.rename", "dictionary", d.id,
                  details={"old": old_name, "new": d.name})
    db.commit()
    return to_out(d)
