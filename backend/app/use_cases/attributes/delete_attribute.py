# Use-case: удаление атрибута (FR-050, US-030 шаг 4) — только СА.
# Запрет при использовании неудалёнными материалами (attribute_values — этап 4);
# привязки к типам удаляются каскадом вместе с атрибутом.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, not_found


def delete_attribute(db: Session, is_super: bool, attribute_id: str) -> None:
    require_super(is_super)
    a = db.execute(
        select(models.Attribute).where(models.Attribute.id == parse_uuid(attribute_id))
    ).scalar_one_or_none()
    if a is None:
        raise not_found("Атрибут не найден")
    if hasattr(models, "AttributeValue"):
        used = db.execute(
            select(models.AttributeValue.id).where(
                models.AttributeValue.material_id.in_(
                    select(models.Material.id).where(models.Material.is_deleted.is_(False))
                ),
                models.AttributeValue.attribute_id == a.id,
            ).limit(1)
        ).first()
        if used:
            raise DomainError(
                status=409, code="ENTITY_IN_USE", title="Удаление невозможно",
                detail="Атрибут используется неудалёнными материалами",
            )
    db.delete(a)
    db.commit()
