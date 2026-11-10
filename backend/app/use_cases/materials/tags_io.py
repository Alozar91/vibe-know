# Теги материала (FR-052, US-031 шаг 4): выбор из словаря, лимит 20.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid
from app.use_cases.errors import DomainError

TAGS_MAX = 20  # tags_max (FR-052), параметр §2.5


def apply_tags(db: Session, m: models.Material, tag_ids: list[str]) -> None:
    """Замена набора тегов материала (PUT-семантика)."""
    ids = []
    for tid in tag_ids or []:
        u = parse_uuid(str(tid))
        if u is None:
            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail=f"Некорректный id тега: {tid}")
        ids.append(u)
    if len(set(ids)) > TAGS_MAX:
        raise DomainError(status=409, code="TAGS_LIMIT_EXCEEDED", title="Превышен лимит тегов",
                          detail=f"Не более {TAGS_MAX} тегов на материал")
    # Все теги должны существовать (словарь глобальный, FR-052)
    found = set(db.execute(
        select(models.Tag.id).where(models.Tag.id.in_(ids))
    ).scalars())
    unknown = [str(x) for x in ids if x not in found]
    if unknown:
        raise DomainError(status=404, code="RESOURCE_NOT_FOUND", title="Объект не найден",
                          detail=f"Теги не найдены: {', '.join(unknown[:3])}")

    db.execute(
        models.MaterialTag.__table__.delete().where(models.MaterialTag.material_id == m.id)
    )
    for tid in set(ids):
        db.add(models.MaterialTag(material_id=m.id, tag_id=tid))


def tag_ids_of(db: Session, material_id) -> list:
    return list(
        db.execute(
            select(models.MaterialTag.tag_id).where(models.MaterialTag.material_id == material_id)
        ).scalars()
    )
