# Use-case: исключение атрибута из типа (FR-051, US-030 шаг 5) — только СА.
# Значения материалов не удаляются: «осиротевшие» — только чтение + поиск (FR-051, 16.1-115).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import not_found


def unbind_attribute(db: Session, is_super: bool, type_id: str, attribute_id: str) -> None:
    require_super(is_super)
    binding = db.execute(
        select(models.AttributeTypeBinding).where(
            models.AttributeTypeBinding.type_id == parse_uuid(type_id),
            models.AttributeTypeBinding.attribute_id == parse_uuid(attribute_id),
        )
    ).scalar_one_or_none()
    if binding is None:
        raise not_found("Привязка не найдена")
    db.delete(binding)
    db.commit()
