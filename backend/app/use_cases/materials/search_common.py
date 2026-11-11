# Этап 8: пересчёт FTS-вектора материала (LLD §7.1).
#
# search_tsv — НЕ generated (зависит от динамической конфигурации):
# пересчитывается сервисом при каждой мутации, влияющей на выдачу:
# название, текст, атрибуты, теги, значение «Язык», тип (состав атрибутов),
# справочники (переименование значений), конфигурация FTS (US-048) —
# плюс периодическая полная пересборка maintenance.fts_rebuild (§9).
#
# Портируемость: на PostgreSQL — полный setweight(to_tsvector(...)) по
# конфигурации search_lang; на SQLite (тесты) — заглушка (вектор не пишется),
# FTS-ветка проверяется приёмкой на живом стеке (как файловый конвейер — этап 6).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models

# Конфигурации FTS (system_settings.fts_languages, FR-122; сид §2.5)
FTS_LANGUAGES = ("russian", "english")

# Фолбэк-мэппинг: язык вне конфигурации → simple — без стемминга (9.7)
_KNOWN_LANGS = {
    "russian": "russian",
    "english": "english",
}


def resolve_search_lang(db: Session, material: models.Material) -> str:
    """Конфигурация FTS материала (FR-122, 9.7):
    атрибут «Язык» не задан → russian; язык вне конфигурации → simple."""
    attr = db.execute(
        select(models.Attribute).where(models.Attribute.name == "Язык")
    ).scalar_one_or_none()
    if attr is None:
        return "russian"
    av = db.execute(
        select(models.AttributeValue).where(
            models.AttributeValue.material_id == material.id,
            models.AttributeValue.attribute_id == attr.id,
        )
    ).scalar_one_or_none()
    if av is None or av.dictionary_value_id is None:
        return "russian"
    dv = db.execute(
        select(models.DictionaryValue).where(models.DictionaryValue.id == av.dictionary_value_id)
    ).scalar_one_or_none()
    if dv is None:
        return "russian"
    lang = (dv.value or "").strip().lower()
    if lang in _KNOWN_LANGS:
        return _KNOWN_LANGS[lang]
    return "simple"


def _attribute_text(db: Session, material_id) -> str:
    """Строковые представления значений атрибутов (вес B, 16.1-115 —
    включая «осиротевшие» значения атрибутов, исключённых из типа)."""
    rows = db.execute(
        select(models.AttributeValue)
        .where(models.AttributeValue.material_id == material_id)
    ).scalars().all()
    parts: list[str] = []
    for av in rows:
        if av.value_string is not None:
            parts.append(av.value_string)
        elif av.dictionary_value_id is not None:
            dv = db.execute(
                select(models.DictionaryValue).where(
                    models.DictionaryValue.id == av.dictionary_value_id
                )
            ).scalar_one_or_none()
            if dv is not None:
                parts.append(dv.value)
        elif av.value_number is not None:
            parts.append(str(av.value_number))
        elif av.value_date is not None:
            parts.append(av.value_date.date().isoformat())
        elif av.value_url is not None:
            parts.append(av.value_url)
    return " ".join(parts)


def _tags_text(db: Session, material_id) -> str:
    """Названия тегов (вес B)."""
    rows = db.execute(
        select(models.Tag.name)
        .join(models.MaterialTag, models.MaterialTag.tag_id == models.Tag.id)
        .where(models.MaterialTag.material_id == material_id)
    ).scalars().all()
    return " ".join(rows)


def build_tsv_sql_expr(cfg: str):
    """SQL-выражение setweight-конкатенации для одной конфигурации (§7.1).

    Возвращает SQLAlchemy-выражение над materials (алиас не нужен —
    коррелированные подзапросы по material_id = m.id).
    Вес D (16.1-121, шаг [8]) — извлечённый текст файла: текущий файл
    материала из кэша file_texts (state='ready'); файла нет / извлечение
    не готово или не удалось — вклад пуст.
    """
    from sqlalchemy import text as sa_text

    return sa_text(f"""
        setweight(to_tsvector('{cfg}', coalesce(materials.name, '')), 'A')
        || setweight(to_tsvector('{cfg}', coalesce((
            SELECT string_agg(
                coalesce(v.value_string, '') || ' ' ||
                coalesce(dv.value, '') || ' ' ||
                coalesce(v.value_number::text, '') || ' ' ||
                coalesce(to_char(v.value_date, 'YYYY-MM-DD'), '') || ' ' ||
                coalesce(v.value_url, ''), ' ')
            FROM attribute_values v
            LEFT JOIN dictionary_values dv ON dv.id = v.dictionary_value_id
            WHERE v.material_id = materials.id
        ), '')), 'B')
        || setweight(to_tsvector('{cfg}', coalesce((
            SELECT string_agg(tg.name, ' ')
            FROM material_tags mt
            JOIN tags tg ON tg.id = mt.tag_id
            WHERE mt.material_id = materials.id
        ), '')), 'B')
        || setweight(to_tsvector('{cfg}', coalesce(materials.text_content, '')), 'C')
        || setweight(to_tsvector('{cfg}', coalesce((
            SELECT ft.text
            FROM file_texts ft
            JOIN file_objects fo ON fo.id = ft.file_id
            WHERE materials.current_file_id = fo.id
              AND ft.state = 'ready'
        ), '')), 'D')
    """)


def update_search_vector(db: Session, material: models.Material) -> None:
    """Пересчёт search_lang + search_tsv одного материала (в транзакции вызывающего).

    SQLite: вектор не считается (нет tsvector) — search_lang проставляется.
    """
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        material.search_lang = resolve_search_lang(db, material)
        return

    from sqlalchemy import text as sa_text

    cfg = resolve_search_lang(db, material)
    material.search_lang = cfg
    db.execute(
        sa_text(f"""
            UPDATE materials SET search_tsv = {build_tsv_sql_expr(cfg).text}
            WHERE id = :mid
        """).bindparams(mid=material.id)
    )
