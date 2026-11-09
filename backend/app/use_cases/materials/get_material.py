# Use-case: карточка материала (FR-026, US-037) — видимость §3.2 + права (FR-129).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.errors import not_found
from app.use_cases.materials.dto import to_card
from app.use_cases.materials.attributes_io import _VALUE_FIELDS
from app.use_cases.permissions.can import can, effective_permissions


def get_material_or_404(db: Session, user, material_id: str, permission: str = "view") -> models.Material:
    """Материал, видимый пользователю; иначе 404 (FR-067: невидим = не найден)."""
    m = db.execute(
        select(models.Material).where(models.Material.id == parse_uuid_safe(material_id))
    ).scalar_one_or_none()
    if m is None or m.is_deleted:
        raise not_found("Материал не найден")
    if not can(db, user, m.id, permission):
        # FR-067: прямая ссылка на невидимый материал — 403; но для списков/карточки
        # LLD §12.1: 403 — нет права или объект невидим. Различаем: не существует/удалён — 404.
        raise not_found("Материал не найден")
    return m


def parse_uuid_safe(v: str):
    from app.use_cases.common import parse_uuid

    u = parse_uuid(v)
    if u is None:
        raise not_found("Материал не найден")
    return u


def get_material(db: Session, user, material_id: str) -> dict:
    """Карточка: поля + атрибуты (+осиротевшие, только чтение — FR-051) + теги + права."""
    m = get_material_or_404(db, user, material_id)
    t = db.execute(
        select(models.MaterialType).where(models.MaterialType.id == m.type_id)
    ).scalar_one()

    bound_ids = {str(b.attribute_id) for b in t.bindings}
    attrs_out = []
    seen = set()
    rows = db.execute(
        select(models.AttributeValue, models.Attribute)
        .join(models.Attribute, models.Attribute.id == models.AttributeValue.attribute_id)
        .where(models.AttributeValue.material_id == m.id)
        .order_by(models.Attribute.display_order, models.Attribute.name)
    ).all()
    # Резолв значений справочника в текст (FR-049, US-031): словарь id → значение
    dv_ids = {av.dictionary_value_id for av, _a in rows if av.dictionary_value_id is not None}
    dv_map = {}
    if dv_ids:
        dv_rows = db.execute(
            select(models.DictionaryValue).where(models.DictionaryValue.id.in_(dv_ids))
        ).scalars().all()
        dv_map = {str(dv.id): dv.value for dv in dv_rows}
    for av, a in rows:
        orphan = str(a.id) not in bound_ids  # атрибут исключён из типа (FR-051)
        field = _VALUE_FIELDS[
            a.value_type.value if hasattr(a.value_type, "value") else str(a.value_type)
        ]
        val = getattr(av, field)
        if val is not None:
            # dictionary-значение отдаётся текстом (значение справочника)
            if field == "dictionary_value_id":
                val = dv_map.get(str(val), str(val))
            entry = next((x for x in attrs_out if x["attribute_id"] == str(a.id)), None)
            if entry is None:
                entry = {
                    "attribute_id": str(a.id),
                    "name": a.name,
                    "value_type": a.value_type.value if hasattr(a.value_type, "value") else str(a.value_type),
                    "is_multivalue": a.is_multivalue,
                    "is_required": a.is_required,
                    "readonly": orphan,
                    "values": [],
                }
                attrs_out.append(entry)
            entry["values"].append(
                str(val) if not hasattr(val, "isoformat") else val.isoformat()
            )
            seen.add(str(a.id))

    tag_ids = [str(x) for x in db.execute(
        select(models.MaterialTag.tag_id).where(models.MaterialTag.material_id == m.id)
    ).scalars()]

    out = to_card(m, effective_permissions(db, user, m.id)) | {
        "type_name": t.name,
        "attributes": attrs_out,
        "tag_ids": tag_ids,
    }

    # FR-126 (4.3): ссылка на мастера или список подчинённых
    out["master_id"] = str(m.master_id) if m.master_id else None
    out["master"] = None
    if m.master_id is not None:
        master = db.execute(
            select(models.Material).where(models.Material.id == m.master_id)
        ).scalar_one_or_none()
        if master is not None and not master.is_deleted:
            out["master"] = {
                "id": str(master.id), "name": master.name,
                "status": master.status.value if hasattr(master.status, "value") else str(master.status),
            }
    children = db.execute(
        select(models.Material)
        .where(models.Material.master_id == m.id, models.Material.is_deleted.is_(False))
        .order_by(models.Material.updated_at.desc())
    ).scalars().all()
    out["children"] = [
        {"id": str(ch.id), "name": ch.name,
         "status": ch.status.value if hasattr(ch.status, "value") else str(ch.status),
         "group_id": str(ch.group_id)}
        for ch in children
    ]
    return out
