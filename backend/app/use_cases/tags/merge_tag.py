# Use-case: слияние тегов (FR-053, US-033 шаг 3) — только СА.
# UPDATE material_tags.tag_id на целевой в одной транзакции с удалением исходного тега (LLD §2.2).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, not_found
from app.use_cases.lifecycle.audit import audit_log


def merge_tag(db: Session, is_super: bool, tag_id: str, target_id: str, actor=None) -> dict:
    require_super(is_super)
    if tag_id == target_id:
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Нельзя слить тег с самим собой")
    src = db.execute(
        select(models.Tag).where(models.Tag.id == parse_uuid(tag_id))
    ).scalar_one_or_none()
    target = db.execute(
        select(models.Tag).where(models.Tag.id == parse_uuid(target_id))
    ).scalar_one_or_none()
    if src is None or target is None:
        raise not_found("Тег не найден")

    # material_tags — этап 4; сейчас переносить нечего, тег просто удаляется
    if hasattr(models, "MaterialTag"):
        # Перенос ссылок: существующие (material, target) не дублируем — UNIQUE
        src_links = db.execute(
            select(models.MaterialTag).where(models.MaterialTag.tag_id == src.id)
        ).scalars().all()
        for link in src_links:
            dup = db.execute(
                select(models.MaterialTag).where(
                    models.MaterialTag.material_id == link.material_id,
                    models.MaterialTag.tag_id == target.id,
                )
            ).scalar_one_or_none()
            if dup:
                db.delete(link)
            else:
                link.tag_id = target.id
    db.delete(src)
    # Этап 8: слияние меняет состав тегов материалов → пересчёт их векторов (LLD §7.1)
    from app.use_cases.materials.search_common import update_search_vector

    for link in db.execute(
        select(models.MaterialTag).where(models.MaterialTag.tag_id == target.id)
    ).scalars().all():
        m = db.execute(
            select(models.Material).where(models.Material.id == link.material_id)
        ).scalar_one_or_none()
        if m is not None:
            update_search_vector(db, m)
    # US-049 ш.1 (FR-140, LLD §11 tag.merge)
    if actor is not None:
        audit_log(db, actor, "tag.merge", "tag", target.id,
                  details={"source": str(src.id), "source_name": src.name,
                           "target_name": target.name})
    db.commit()
    return {"merged_into": str(target.id), "name": target.name}
