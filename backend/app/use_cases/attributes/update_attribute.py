# Use-case: правка атрибута (FR-045, US-030 шаг 3) — только СА.
# Изменяемо: name, is_required, display_order. Неизменяемо: value_type, is_multivalue (FR-045).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.attributes.dto import to_out
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, name_conflict, not_found


def update_attribute(
    db: Session,
    is_super: bool,
    attribute_id: str,
    name: str | None = None,
    is_required: bool | None = None,
    display_order: int | None = None,
) -> dict:
    require_super(is_super)
    a = db.execute(
        select(models.Attribute).where(models.Attribute.id == parse_uuid(attribute_id))
    ).scalar_one_or_none()
    if a is None:
        raise not_found("Атрибут не найден")
    if name is not None:
        if not name.strip():
            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail="Название атрибута обязательно")
        dup = db.execute(
            select(models.Attribute).where(
                models.Attribute.name == name.strip(), models.Attribute.id != a.id
            )
        ).scalar_one_or_none()
        if dup:
            raise name_conflict("Атрибут с таким названием уже существует")
        a.name = name.strip()
    # is_required изменяем; действует для последующих сохранений (FR-045)
    if is_required is not None:
        a.is_required = is_required
    if display_order is not None:
        a.display_order = display_order
    db.commit()
    return to_out(a)
