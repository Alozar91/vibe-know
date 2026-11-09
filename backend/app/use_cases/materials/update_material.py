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
    """Правка метаданных/текста (US-009 шаг «редактирование по статусам» — этап 5
    уточнит допустимость по статусу; здесь — право edit + If-Match)."""
    m = get_material_or_404(db, user, material_id)
    _require_edit(db, user, m)
    _require_if_match(if_match)
    _check_version(m, _parse_version(if_match))

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
        from app.use_cases.materials.attributes_io import missing_required

        missing = missing_required(db, m, t_now)
        if missing:
            raise DomainError(
                status=409, code="ATTRIBUTE_REQUIRED_MISSING", title="Не заполнены обязательные атрибуты",
                detail="Заполните обязательные атрибуты", params={"missing": missing},
            )
        m.last_editor_id = user.user_id
        m.version += 1
        m.updated_at = datetime.now(timezone.utc)

    db.commit()
    return {"id": str(m.id), "version": m.version}
