# Use-case: создание материала (FR-024–027, US-007 шаги 1–2/6 без файла — этап 6).
# Право «Создание» в группе (FR-026/108); уникальность имени в группе (FR-027);
# обязательные атрибуты типа (FR-048) — при сохранении карточки, здесь — тоже.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super  # noqa: F401
from app.use_cases.errors import DomainError, access_denied, name_conflict, not_found
from app.use_cases.groups.create_group import normalize_name
from app.use_cases.materials.constants import NAME_MAX_LEN
from app.use_cases.materials.dto import to_out
from app.use_cases.permissions.can import can_group

from datetime import datetime, timezone


def require_group_create(db: Session, user, group_id) -> models.Group:
    """Право create на группу (FR-026); СА — в обход (FR-104)."""
    if not can_group(db, user, group_id, "create"):
        raise access_denied("Нет права «Создание» в группе")
    g = db.execute(
        select(models.Group).where(
            models.Group.id == parse_uuid(str(group_id)),
            models.Group.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if g is None:
        raise not_found("Группа не найдена")
    return g


def validate_name(name: str) -> str:
    if not name or not name.strip():
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Название материала обязательно")
    if len(name.strip()) > NAME_MAX_LEN:
        raise DomainError(status=400, code="NAME_TOO_LONG", title="Ошибка валидации запроса",
                          detail=f"Название превышает {NAME_MAX_LEN} символов")
    return name.strip()


def ensure_name_free(db: Session, group_id, name: str, exclude_id=None) -> None:
    """Уникальность имени среди неудалённых материалов группы (FR-027)."""
    stmt = select(models.Material.id).where(
        models.Material.group_id == group_id,
        models.Material.normalized_name == normalize_name(name),
        models.Material.is_deleted.is_(False),
    )
    if exclude_id is not None:
        stmt = stmt.where(models.Material.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise name_conflict("Материал с таким названием уже существует в группе")


def create_material(
    db: Session,
    user,
    group_id: str,
    name: str,
    type_id: str,
    text_content: str | None = None,
    attribute_values: list[dict] | None = None,
    tag_ids: list[str] | None = None,
) -> dict:
    """Создание (в т.ч. «пустышка» без файла — FR-026): draft, версия 1 (FR-144)."""
    g = require_group_create(db, user, group_id)

    t = db.execute(
        select(models.MaterialType).where(models.MaterialType.id == parse_uuid(type_id))
    ).scalar_one_or_none()
    if t is None:
        raise not_found("Тип материала не найден")

    clean_name = validate_name(name)
    ensure_name_free(db, g.id, clean_name)

    # Валидация обязательных атрибутов ДО записи (FR-048): missing = required,
    # не покрытые значениями запроса; материал не создаётся вовсе
    from app.use_cases.materials.attributes_io import missing_required_for_new

    t_attrs = db.execute(
        select(models.Attribute).join(
            models.AttributeTypeBinding,
            models.AttributeTypeBinding.attribute_id == models.Attribute.id,
        ).where(models.AttributeTypeBinding.type_id == t.id)
    ).scalars().all()
    supplied: dict = {}
    for item in attribute_values or []:
        aid = str(parse_uuid(str(item.get("attribute_id"))))
        supplied[aid] = item.get("values") or []
    missing = [a.name for a in t_attrs if a.is_required and not supplied.get(str(a.id))]
    if missing:
        raise DomainError(
            status=409, code="ATTRIBUTE_REQUIRED_MISSING", title="Не заполнены обязательные атрибуты",
            detail="Заполните обязательные атрибуты", params={"missing": missing},
        )

    now = datetime.now(timezone.utc)
    m = models.Material(
        group_id=g.id,
        name=clean_name,
        normalized_name=normalize_name(clean_name),
        type_id=t.id,
        status=models.MaterialStatus.draft,
        author_id=user.user_id,
        last_editor_id=user.user_id,
        text_content=text_content,
        version=1,
        updated_at=now,  # FR-026: даты создания/изменения фиксируются при создании
    )
    db.add(m)
    db.flush()

    if attribute_values:
        from app.use_cases.materials.attributes_io import apply_attribute_values

        apply_attribute_values(db, m, t, attribute_values)
    if tag_ids:
        from app.use_cases.materials.tags_io import apply_tags

        apply_tags(db, m, tag_ids)

    # Версия 1 (FR-144, US-007 шаг 6): снапшот после записи атрибутов/тегов
    from app.use_cases.materials.versions import snapshot_from_material, commit_version

    commit_version(db, m, user, snapshot=snapshot_from_material(db, m))

    # Этап 8: первичный FTS-вектор (LLD §7.1 — пересчёт при записи)
    from app.use_cases.materials.search_common import update_search_vector

    update_search_vector(db, m)

    # Пост-MVP [7]: RAG-хук (§5) — pending для конвейера индексации
    from app.rag.indexing import flush_rag_enqueue, hook_after_change

    hook_after_change(db, m)

    db.commit()
    flush_rag_enqueue(db)  # постановка в брокер — после коммита (§9)
    return to_out(m)
