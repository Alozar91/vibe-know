# Use-case: удаление тега (FR-054, US-033 шаг 4) — только СА.
# Запрет при использовании неудалёнными материалами (material_tags — этап 4).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, not_found
from app.use_cases.lifecycle.audit import audit_log


def delete_tag(db: Session, is_super: bool, tag_id: str, actor=None) -> None:
    require_super(is_super)
    t = db.execute(
        select(models.Tag).where(models.Tag.id == parse_uuid(tag_id))
    ).scalar_one_or_none()
    if t is None:
        raise not_found("Тег не найден")
    if hasattr(models, "MaterialTag"):
        used = db.execute(
            select(models.MaterialTag.material_id).where(
                models.MaterialTag.tag_id == t.id,
                models.MaterialTag.material_id.in_(
                    select(models.Material.id).where(models.Material.is_deleted.is_(False))
                ),
            ).limit(1)
        ).first()
        if used:
            raise DomainError(
                status=409, code="ENTITY_IN_USE", title="Удаление невозможно",
                detail="Тег используется неудалёнными материалами",
            )
    name = t.name
    tid = t.id
    db.delete(t)
    # US-049 ш.1 (FR-140, LLD §11 tag.delete)
    if actor is not None:
        audit_log(db, actor, "tag.delete", "tag", tid, details={"name": name})
    db.commit()
