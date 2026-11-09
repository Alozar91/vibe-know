# Use-case: правка материала (FR-026/027/048/049, US-009/031/032; If-Match — FR-095).
# Этап 4: правки имени/текста/типа/атрибутов/тегов; переходы статусов — этап 5.
# ETag/version: каждое сохранение инкрементирует version (FR-093–095); снапшот
# версии — этап 6 (материалы без файлов сейчас фиксируются как version+1).
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid
from app.use_cases.errors import DomainError, access_denied, not_found
from app.use_cases.materials.constants import NAME_MAX_LEN
from app.use_cases.materials.create_material import (
    ensure_name_free,
    validate_name,
)
from app.use_cases.materials.get_material import get_material_or_404
from app.use_cases.groups.create_group import normalize_name
from app.use_cases.permissions.can import can


def _require_edit(db: Session, user, m: models.Material) -> None:
    """Право edit на материал (§3.2; FR-102)."""
    if not can(db, user, m.id, "edit"):
        raise access_denied("Нет права «Редактирование» на материал")


def _require_if_match(if_match: str | None) -> None:
    """Мутация без If-Match — 428 (FR-095, LLD §12.1)."""
    if if_match is None or not if_match.strip():
        raise DomainError(
            status=428, code="PRECONDITION_REQUIRED", title="Требуется If-Match",
            detail="Передайте заголовок If-Match с текущей версией материала",
        )


def _parse_version(if_match: str) -> int:
    v = if_match.strip().strip('"')
    try:
        return int(v)
    except ValueError:
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail="If-Match должен содержать номер версии",
        )


def _check_version(m: models.Material, expected: int) -> None:
    """Конкурентное редактирование (FR-093/095): не совпало → 412."""
    if m.version != expected:
        raise DomainError(
            status=412, code="VERSION_CONFLICT", title="Конфликт версии",
            detail=f"Материал изменён (текущая версия {m.version}); обновите карточку",
        )


def _block_master_with_published_children(db: Session, m: models.Material) -> None:
    """FR-041 (§4.3): правка контента мастера с подчинёнными в «Публикации»
    блокируется тем же валидатором, что и смена статуса."""
    from app.use_cases.errors import master_status_locked

    has_published_children = db.execute(
        select(models.Material.id).where(
            models.Material.master_id == m.id,
            models.Material.is_deleted.is_(False),
            models.Material.status == models.MaterialStatus.published,
        ).limit(1)
    ).first()
    if has_published_children:
        raise master_status_locked()


def update_material(
    db: Session,
    user,
    material_id: str,
    if_match: str | None,
    name: str | None = None,
    type_id: str | None = None,
    text_content: str | None = None,
    attribute_values: list[dict] | None = None,
    tag_ids: list[str] | None = None,
) -> dict:
    """Правка материала (US-009, §4.2 «правки по статусам»):
    - архив — редактирование запрещено (403, FR-087);
    - правка контента (файл — этап 6, текст) в approved/published → возврат
      в draft + очистка подписанта (FR-084); в in_review — статус сохраняется
      (FR-085; событие уведомления — этап 9);
    - правка только метаданных (название/тип/атрибуты/теги) статусы не снимает;
    - мастер с подчинёнными в «Публикации»: правка контента блокируется (FR-041)."""
    m = get_material_or_404(db, user, material_id)
    _require_edit(db, user, m)
    _require_if_match(if_match)
    _check_version(m, _parse_version(if_match))

    status_v = m.status.value if hasattr(m.status, "value") else str(m.status)
    if status_v == "archived":
        # FR-087: в архиве недоступно любое редактирование (контент и метаданные)
        raise access_denied("Материал в архиве; редактирование запрещено")

    content_changed = text_content is not None and text_content != m.text_content
    if content_changed and status_v in ("published", "approved") and m.master_id is None:
        # Валидатор 5 (FR-041): мастер/самостоятельный с подчинёнными в published —
        # контент не правится (иначе возврат в draft нарушил бы инвариант)
        _block_master_with_published_children(db, m)

    changed = False
    type_changed = False

    if name is not None and name.strip() != m.name:
        clean = validate_name(name)
        if clean != m.name:
            ensure_name_free(db, m.group_id, clean, exclude_id=m.id)
            m.name = clean
            m.normalized_name = normalize_name(clean)
            changed = True

    if type_id is not None and parse_uuid(type_id) != m.type_id:
        t_new = db.execute(
            select(models.MaterialType).where(models.MaterialType.id == parse_uuid(type_id))
        ).scalar_one_or_none()
        if t_new is None:
            raise not_found("Тип материала не найден")
        m.type_id = t_new.id  # смена типа (US-032): значения прежнего типа остаются (FR-051)
        type_changed = True
        changed = True

    if text_content is not None and text_content != m.text_content:
        m.text_content = text_content
        changed = True

    t_now = db.execute(
        select(models.MaterialType).where(models.MaterialType.id == m.type_id)
    ).scalar_one()

    if attribute_values is not None:
        from app.use_cases.materials.attributes_io import apply_attribute_values

        apply_attribute_values(db, m, t_now, attribute_values)
        changed = True

    if tag_ids is not None:
        from app.use_cases.materials.tags_io import apply_tags

        apply_tags(db, m, tag_ids)
        changed = True

    if changed:
        # FR-049: обязательные атрибуты действующего типа проверяются в том же
        # сохранении (в т.ч. при смене типа — US-032 шаг 2)
        from app.use_cases.lifecycle.audit import audit_log
        from app.use_cases.materials.attributes_io import missing_required

        missing = missing_required(db, m, t_now)
        if missing:
            raise DomainError(
                status=409, code="ATTRIBUTE_REQUIRED_MISSING", title="Не заполнены обязательные атрибуты",
                detail="Заполните обязательные атрибуты", params={"missing": missing},
            )

        # §4.2: правка контента по статусам (FR-084/085); контент сейчас —
        # только текстовое представление (файл — этап 6)
        new_status = status_v
        if content_changed:
            if status_v in ("published", "approved"):
                new_status = "draft"
            # in_review: статус сохраняется (FR-085); draft — без изменений

        now = datetime.now(timezone.utc)
        if new_status != status_v:
            from app.use_cases.lifecycle.status_log import write_status_log

            write_status_log(db, user, m, status_v, new_status)
            audit_log(
                db, user, "material.status_change", "material", m.id,
                details={"from": status_v, "to": new_status, "reason": "content_edit"},
            )
            m.status = models.MaterialStatus(new_status)
            m.signatory_id = None  # FR-084: очистка подписанта
            m.signatory_at = None
        elif content_changed and status_v == "in_review":
            # FR-085: аудит правки на ревью; уведомление material_changed_on_review — этап 9
            audit_log(db, user, "material.update", "material", m.id,
                      details={"on_review": True})
        else:
            audit_log(db, user, "material.update", "material", m.id)

        m.last_editor_id = user.user_id
        m.version += 1
        m.updated_at = now

    db.commit()
    return {"id": str(m.id), "version": m.version}
