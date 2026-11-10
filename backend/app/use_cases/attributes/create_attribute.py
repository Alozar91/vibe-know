# Use-case: создание атрибута (FR-044, US-030 шаг 1) — только СА.
# value_type/is_multivalue неизменяемы после создания (FR-045) — исправить нельзя, только пересоздать.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.attributes.dto import MULTIVALUE_ALLOWED, VALUE_TYPES, to_out
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, name_conflict
from app.use_cases.lifecycle.audit import audit_log


def create_attribute(
    db: Session,
    is_super: bool,
    name: str,
    value_type: str,
    is_multivalue: bool = False,
    is_required: bool = False,
    display_order: int = 0,
    dictionary_id: str | None = None,
    actor=None,
) -> dict:
    require_super(is_super)
    if not name or not name.strip():
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Название атрибута обязательно")
    if value_type not in VALUE_TYPES:
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail=f"Тип значения должен быть одним из: {', '.join(VALUE_TYPES)}")
    if is_multivalue and value_type not in MULTIVALUE_ALLOWED:
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Многозначность допустима только для строк, ссылок и справочников")
    if value_type == "dictionary":
        if not dictionary_id:
            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail="Для типа «справочник» требуется dictionary_id")
        d = db.execute(
            select(models.Dictionary).where(models.Dictionary.id == parse_uuid(dictionary_id))
        ).scalar_one_or_none()
        if d is None:
            raise DomainError(status=404, code="RESOURCE_NOT_FOUND", title="Объект не найден",
                              detail="Справочник не найден")
    if db.execute(select(models.Attribute).where(models.Attribute.name == name.strip())).scalar_one_or_none():
        raise name_conflict("Атрибут с таким названием уже существует")

    a = models.Attribute(
        name=name.strip(),
        value_type=models.AttrValueType(value_type),
        is_multivalue=is_multivalue,
        is_required=is_required,
        display_order=display_order,
        dictionary_id=parse_uuid(dictionary_id) if dictionary_id else None,
    )
    db.add(a)
    db.flush()
    # US-049 ш.1 (FR-140, LLD §11 attribute.create)
    if actor is not None:
        audit_log(db, actor, "attribute.create", "attribute", a.id,
                  details={"name": a.name, "value_type": value_type})
    db.commit()
    return to_out(a)
