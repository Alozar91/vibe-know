# Версионирование (LLD §5.1, FR-144–148): снапшот материала и фиксация версий.
#
# Снапшот (состав FR-144): {"file_id", "text", "name", "type_id",
# "attributes": [{attribute_id, values[]}], "tags"} — без master_id и прав.
# Фиксация: при каждом сохранении (контент или метаданные) — сравнение с
# последней версией (значения атрибутов упорядочены, текст как есть); при
# различии — новая версия number = max + 1. Статусы/права/подписант/master_id
# версией не являются. Файл: при замене — новый file_id; при неизменности —
# ссылка на прежний FileObject (дедупликация, FR-147).
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.materials.attributes_io import _VALUE_FIELDS


def serialize_snapshot(
    db: Session,
    file_id: str | None,
    text: str | None,
    name: str,
    type_id,
    material_id=None,
    attributes: list[dict] | None = None,
    tag_ids: list | None = None,
) -> dict:
    """Сериализация снапшота из БД (значения атрибутов — упорядоченно, §5.1).

    attributes/tag_ids передаются, когда значения ещё не зафиксированы
    (создание); иначе читаются из БД по material_id.
    """
    if attributes is None:
        rows = db.execute(
            select(models.AttributeValue)
            .where(models.AttributeValue.material_id == material_id)
            .order_by(models.AttributeValue.attribute_id, models.AttributeValue.id)
        ).scalars().all()
        grouped: dict[str, list] = {}
        for av in rows:
            grouped.setdefault(str(av.attribute_id), []).append(_value_repr(av))
        attributes = [
            {"attribute_id": aid, "values": vals}
            for aid, vals in sorted(grouped.items())
        ]
    else:
        # нормализация входа: атрибуты упорядочены по attribute_id, значения как есть
        attributes = sorted(
            ({"attribute_id": str(a["attribute_id"]), "values": list(a.get("values") or [])}
             for a in attributes),
            key=lambda a: a["attribute_id"],
        )

    return {
        "file_id": str(file_id) if file_id else None,
        "text": text,
        "name": name,
        "type_id": str(type_id),
        "attributes": attributes,
        "tags": sorted(str(t) for t in (tag_ids or [])),
    }


def _value_repr(av: models.AttributeValue):
    """Строковое представление значения (по колонке типа, LLD §2.2)."""
    for field in ("value_string", "value_number", "value_date", "value_url", "dictionary_value_id"):
        v = getattr(av, field)
        if v is not None:
            if hasattr(v, "isoformat"):
                return v.isoformat()
            if field == "value_number":
                # numeric: стабильное сравнение с float-значениями из API
                return float(v)
            return str(v)
    return None


def snapshot_from_material(db: Session, m: models.Material, attributes: list[dict] | None = None,
                           tag_ids: list | None = None) -> dict:
    """Снапшот текущего состояния материала (файл/текст/имя/тип из записи)."""
    return serialize_snapshot(
        db,
        file_id=str(m.current_file_id) if m.current_file_id else None,
        text=m.text_content,
        name=m.name,
        type_id=str(m.type_id),
        material_id=m.id,
        attributes=attributes,
        tag_ids=tag_ids if tag_ids is not None else (
            [str(t) for t in db.execute(
                select(models.MaterialTag.tag_id).where(models.MaterialTag.material_id == m.id)
            ).scalars()]
            if m.id is not None else []
        ),
    )


def last_version(db: Session, material_id) -> models.MaterialVersion | None:
    """Последняя версия материала (max number)."""
    return db.execute(
        select(models.MaterialVersion)
        .where(models.MaterialVersion.material_id == material_id)
        .order_by(models.MaterialVersion.number.desc())
        .limit(1)
    ).scalar_one_or_none()


def next_number(db: Session, material_id) -> int:
    row = db.execute(
        select(func.max(models.MaterialVersion.number))
        .where(models.MaterialVersion.material_id == material_id)
    ).scalar_one()
    return (row or 0) + 1


def _normalize(snap: dict) -> dict:
    """Нормализация для сравнения (§5.1): значения атрибутов упорядочены,
    текст как есть; float значениям — единое представление."""
    attrs = sorted(
        (
            {
                "attribute_id": str(a.get("attribute_id")),
                "values": sorted(str(v) for v in (a.get("values") or [])),
            }
            for a in (snap.get("attributes") or [])
        ),
        key=lambda a: a["attribute_id"],
    )
    out = dict(snap)
    out["attributes"] = attrs
    out["tags"] = sorted(str(t) for t in (snap.get("tags") or []))
    return out


def snapshots_differ(a: dict, b: dict) -> bool:
    return _normalize(a) != _normalize(b)


def commit_version(
    db: Session,
    m: models.Material,
    author,
    snapshot: dict | None = None,
) -> models.MaterialVersion | None:
    """Фиксация версии при сохранении (§5.1): сравнение с последней; при
    различии — новая строка number = max + 1. Возвращает новую версию или None.

    Вызывается в транзакции сохранения (create/update/restore); коммит делает
    вызывающий код.
    """
    snap = snapshot or snapshot_from_material(db, m)
    prev = last_version(db, m.id)
    if prev is not None and not snapshots_differ(prev.snapshot, snap):
        return None
    v = models.MaterialVersion(
        material_id=m.id,
        number=next_number(db, m.id),
        snapshot=snap,
        author_id=author.user_id,
    )
    db.add(v)
    return v


def get_version_or_404(db: Session, material_id, number: int) -> models.MaterialVersion:
    from app.use_cases.errors import not_found

    v = db.execute(
        select(models.MaterialVersion).where(
            models.MaterialVersion.material_id == material_id,
            models.MaterialVersion.number == number,
        )
    ).scalar_one_or_none()
    if v is None:
        raise not_found("Версия не найдена")
    return v
