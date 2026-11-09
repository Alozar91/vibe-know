# Use-case: создание типа материала (FR-043, US-030 шаг 2) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import require_super, validate_permissions  # noqa: F401
from app.use_cases.errors import DomainError, name_conflict
from app.use_cases.types.dto import to_out


def create_type(db: Session, is_super: bool, name: str, attribute_ids: list[str] | None = None) -> dict:
    """Тип не создаёт материалов — СА; атрибуты привязываются сразу или позже (US-030 шаг 2)."""
    require_super(is_super)
    if not name or not name.strip():
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Название типа обязательно")
    if db.execute(select(models.MaterialType).where(models.MaterialType.name == name.strip())).scalar_one_or_none():
        raise name_conflict("Тип с таким названием уже существует")
    t = models.MaterialType(name=name.strip())
    db.add(t)
    db.flush()
    if attribute_ids:
        from app.use_cases.types.bind_attribute import bind_attribute

        for aid in attribute_ids:
            bind_attribute(db, is_super, str(t.id), aid, commit=False)
    db.commit()
    db.expire(t, ["bindings"])  # коллекция наполнялась в этой же транзакции
    return to_out(t)
