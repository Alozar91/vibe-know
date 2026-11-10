# Use-case: удаление значения справочника (FR-047, US-033 шаг 4) — только СА.
# Запрет при использовании неудалёнными материалами (attribute_values — этап 4).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, not_found
from app.use_cases.lifecycle.audit import audit_log


def delete_dictionary_value(db: Session, is_super: bool, value_id: str, actor=None) -> None:
    require_super(is_super)
    v = db.execute(
        select(models.DictionaryValue).where(models.DictionaryValue.id == parse_uuid(value_id))
    ).scalar_one_or_none()
    if v is None:
        raise not_found("Значение не найдено")
    if hasattr(models, "AttributeValue"):
        used = db.execute(
            select(models.AttributeValue.id).where(
                models.AttributeValue.dictionary_value_id == v.id,
                models.AttributeValue.material_id.in_(
                    select(models.Material.id).where(models.Material.is_deleted.is_(False))
                ),
            ).limit(1)
        ).first()
        if used:
            raise DomainError(
                status=409, code="ENTITY_IN_USE", title="Удаление невозможно",
                detail="Значение используется неудалёнными материалами",
            )
    value = v.value
    vid = v.id
    db.delete(v)
    # US-049 ш.1 (FR-140, LLD §11 dictionary.value_delete)
    if actor is not None:
        audit_log(db, actor, "dictionary.value_delete", "dictionary", vid,
                  details={"value": value})
    db.commit()
