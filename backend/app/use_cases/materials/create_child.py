# Use-case: создание подчинённого материала (LLD §12.3; US-024/025; FR-033–035).
#
# Мастер «Утверждён»/«Публикация» и виден (FR-033, 16.1-77); право create в
# целевой группе (FR-108); «Копирование» на мастере не требуется (16.1-25).
# Копия: файл (ref_count+1, без повторного антивируса — FR-057; дедуп —
# NFR-010), текст, тип, атрибуты (в т.ч. «осиротевшие» — FR-051), теги.
# Статус «Черновик», master_id; права — от группы, не от мастера (8.2).
# Вид «перевод»: language_id из справочника атрибута «Язык» → значение
# атрибута (независимо от назначения на тип — 16.1-115) + имя по умолчанию.
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid
from app.use_cases.errors import DomainError, access_denied
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.materials.create_material import require_group_create
from app.use_cases.materials.dto import to_out
from app.use_cases.materials.get_material import get_material_or_404
from app.use_cases.materials.stage7_common import (
    commit_first_version,
    copy_content,
    unique_name,
)

ADAPTATION_SUFFIX = " Адаптация"


def _find_language_attribute(db: Session) -> models.Attribute | None:
    """Атрибут «Язык» стартового набора (FR-046, 16.1-98)."""
    return db.execute(
        select(models.Attribute).where(models.Attribute.name == "Язык")
    ).scalar_one_or_none()


def _language_code(db: Session, language_id) -> str:
    """Код языка для имени перевода — значение справочника («Русский» → RU,
    иначе первый транслит-фолбэк: первые 2 заглавных буквы значения)."""
    dv = db.execute(
        select(models.DictionaryValue).where(models.DictionaryValue.id == parse_uuid(str(language_id)))
    ).scalar_one_or_none()
    if dv is None:
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail="Язык должен быть значением справочника",
        )
    value = dv.value.strip()
    if not value:
        return "??"
    # «код языка»: ASCII-буквы значения, максимум 3 (RU, EN, DE); иначе UPPERCASE-фолбэк
    letters = [c for c in value if c.isascii() and c.isalpha()]
    if letters:
        return ("".join(letters))[:3].upper()
    return value[:2].upper()


def _validate_language(db: Session, language_id, kind: str) -> None:
    """Перевод без языка — нельзя завершить создание (US-025 A1)."""
    if kind != "translation":
        return
    if language_id is None or not str(language_id).strip():
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail="Для перевода требуется указать язык (US-025 A1)",
        )


def _apply_language_value(db: Session, child: models.Material, language_id) -> None:
    """Значение «Языка» записывается независимо от назначения на тип (16.1-115)."""
    attr = _find_language_attribute(db)
    if attr is None:
        # атрибут «Язык» отсутствует в системе (не внедрён) — имя по коду из
        # самого id не построить; считаем это конфигурационной ошибкой
        raise DomainError(
            status=409, code="DOMAIN_RULE_VIOLATION", title="Атрибут «Язык» не найден",
            detail="Создание перевода невозможно: в системе нет атрибута «Язык» (FR-046)",
        )
    # Значение должно быть из справочника атрибута «Язык» (FR-047)
    dv = db.execute(
        select(models.DictionaryValue).where(
            models.DictionaryValue.id == parse_uuid(str(language_id))
        )
    ).scalar_one_or_none()
    if dv is None or str(dv.dictionary_id) != str(attr.dictionary_id):
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail="Язык должен быть значением справочника атрибута «Язык»",
        )
    db.add(models.AttributeValue(
        material_id=child.id, attribute_id=attr.id, dictionary_value_id=dv.id,
    ))


def create_child_material(
    db: Session,
    user,
    material_id: str,
    kind: str,
    group_id: str,
    name: str | None = None,
    language_id: str | None = None,
) -> dict:
    """Создание подчинённого (адаптация/перевод) — US-024/025."""
    if kind not in ("adaptation", "translation"):
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail="kind должен быть «adaptation» или «translation»",
        )
    _validate_language(db, language_id, kind)

    # A2 US-024: право create в целевой группе проверяем до мастера —
    # пользователь с доступом к мастеру, но без create получает 403, а не 409
    g = require_group_create(db, user, group_id)

    # A1 US-024: мастер виден пользователю и в статусе «Утверждён»/«Публикация»
    # (невидим/не существует → 404 по FR-067; чужой статус → 409)
    master = get_material_or_404(db, user, material_id)
    ms = master.status.value if hasattr(master.status, "value") else str(master.status)
    if ms not in ("approved", "published"):
        raise DomainError(
            status=409, code="MASTER_NOT_PUBLISHED", title="Мастер не подходит",
            detail="Подчинённый создаётся от мастера в статусе «Утверждён» или «Публикация»",
        )

    # Имя: по умолчанию по виду (FR-035); счётчик при конфликте — к полному имени
    base = name.strip() if name and name.strip() else (
        f"{master.name}{ADAPTATION_SUFFIX}" if kind == "adaptation"
        else f"{master.name} (Перевод, {_language_code(db, language_id)})"
    )
    final_name = unique_name(db, g.id, base)

    now = datetime.now(timezone.utc)
    from app.use_cases.groups.create_group import normalize_name

    child = models.Material(
        group_id=g.id,
        name=final_name,
        normalized_name=normalize_name(final_name),
        type_id=master.type_id,
        status=models.MaterialStatus.draft,
        master_id=master.id,
        author_id=user.user_id,
        last_editor_id=user.user_id,
        version=1,
        updated_at=now,
    )
    db.add(child)
    db.flush()

    # Копия содержимого (файл ref_count+1, текст, тип, атрибуты, теги)
    copy_content(db, master, child)

    # Перевод: значение «Языка» заменяет скопированное (16.1-115)
    if kind == "translation":
        from sqlalchemy import delete as sa_delete

        lang_attr = _find_language_attribute(db)
        if lang_attr is not None:
            db.execute(
                sa_delete(models.AttributeValue).where(
                    models.AttributeValue.material_id == child.id,
                    models.AttributeValue.attribute_id == lang_attr.id,
                )
            )
        _apply_language_value(db, child, language_id)

    # master_id в снапшот не входит (FR-144) — версия 1 как при создании
    commit_first_version(db, child, user)

    audit_log(db, user, "material.create", "material", child.id,
              details={"kind": kind, "master_id": str(master.id)})

    db.commit()
    return to_out(child)
