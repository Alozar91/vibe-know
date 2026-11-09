# Use-case: привязка атрибута к типу (FR-044, US-030 шаг 2) — только СА.
# Лимит attributes_max_per_type (50) — параметр §2.5; чтение реестра — этап 10, здесь константа.
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, not_found

ATTRIBUTES_MAX_PER_TYPE = 50  # system_settings.attributes_max_per_type (FR-044)


def bind_attribute(
    db: Session, is_super: bool, type_id: str, attribute_id: str, commit: bool = True
) -> None:
    require_super(is_super)
    t = db.execute(
        select(models.MaterialType).where(models.MaterialType.id == parse_uuid(type_id))
    ).scalar_one_or_none()
    if t is None:
        raise not_found("Тип не найден")
    a = db.execute(
        select(models.Attribute).where(models.Attribute.id == parse_uuid(attribute_id))
    ).scalar_one_or_none()
    if a is None:
        raise not_found("Атрибут не найден")

    # Счётчик по БД: коллекция t.bindings может быть неактуальна в рамках транзакции
    count = db.execute(
        select(func.count()).select_from(models.AttributeTypeBinding).where(
            models.AttributeTypeBinding.type_id == t.id
        )
    ).scalar_one()
    if count >= ATTRIBUTES_MAX_PER_TYPE:
        raise DomainError(
            status=409, code="ATTRIBUTES_LIMIT_EXCEEDED", title="Превышен лимит",
            detail=f"На типе уже {ATTRIBUTES_MAX_PER_TYPE} атрибутов",
        )
    exists = db.execute(
        select(models.AttributeTypeBinding).where(
            models.AttributeTypeBinding.type_id == t.id,
            models.AttributeTypeBinding.attribute_id == a.id,
        )
    ).scalar_one_or_none() is not None
    if not exists:
        db.add(models.AttributeTypeBinding(type_id=t.id, attribute_id=a.id))
        db.flush()
        # Этап 8: состав атрибутов типа изменился → пересчёт векторов материалов
        # типа (LLD §7.1 «смена состава атрибутов»)
        from app.use_cases.materials.search_common import update_search_vector

        for m in db.execute(
            select(models.Material).where(
                models.Material.type_id == t.id, models.Material.is_deleted.is_(False)
            )
        ).scalars().all():
            update_search_vector(db, m)
        if commit:
            db.commit()
