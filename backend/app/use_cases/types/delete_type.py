# Use-case: удаление типа (FR-050, US-030 шаг 4) — только СА.
# Запрет при использовании неудалёнными материалами (materials — этап 4).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, domain_rule_violation, not_found


def delete_type(db: Session, is_super: bool, type_id: str) -> None:
    require_super(is_super)
    t = db.execute(
        select(models.MaterialType).where(models.MaterialType.id == parse_uuid(type_id))
    ).scalar_one_or_none()
    if t is None:
        raise not_found("Тип не найден")
    if hasattr(models, "Material"):
        used = db.execute(
            select(models.Material.id).where(
                models.Material.type_id == t.id, models.Material.is_deleted.is_(False)
            ).limit(1)
        ).first()
        if used:
            raise DomainError(
                status=409, code="ENTITY_IN_USE", title="Удаление невозможно",
                detail="Тип назначен неудалённым материалам",
            )
    db.delete(t)
    db.commit()
