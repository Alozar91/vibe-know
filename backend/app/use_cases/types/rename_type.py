# Use-case: переименование типа (FR-043) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, name_conflict, not_found
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.types.dto import to_out


def rename_type(db: Session, is_super: bool, type_id: str, name: str, actor=None) -> dict:
    require_super(is_super)
    t = db.execute(
        select(models.MaterialType).where(models.MaterialType.id == parse_uuid(type_id))
    ).scalar_one_or_none()
    if t is None:
        raise not_found("Тип не найден")
    if not name or not name.strip():
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Название типа обязательно")
    dup = db.execute(
        select(models.MaterialType).where(
            models.MaterialType.name == name.strip(), models.MaterialType.id != t.id
        )
    ).scalar_one_or_none()
    if dup:
        raise name_conflict("Тип с таким названием уже существует")
    old_name = t.name
    t.name = name.strip()
    # US-049 ш.1 (FR-140, LLD §11 type.rename)
    if actor is not None:
        audit_log(db, actor, "type.rename", "type", t.id,
                  details={"old": old_name, "new": t.name})
    db.commit()
    return to_out(t)
