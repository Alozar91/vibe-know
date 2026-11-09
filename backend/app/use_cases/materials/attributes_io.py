# Ввод/вывод значений атрибутов материала (FR-048/049/051, US-031/032).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid
from app.use_cases.errors import DomainError

# Тип колонки по value_type (LLD §2.2 attribute_values)
_VALUE_FIELDS = {
    "string": "value_string",
    "number": "value_number",
    "date": "value_date",
    "url": "value_url",
    "dictionary": "dictionary_value_id",
}


def apply_attribute_values(
    db: Session, m: models.Material, t: models.MaterialType, values: list[dict]
) -> None:
    """Замена значений атрибутов материала (PUT-семантика карточки, US-031).

    values: [{attribute_id, values: [ ... ]}] — многозначность = несколько строк.
    «Осиротевшие» (атрибут исключён из типа) не перезаписываются (FR-051):
    вход содержит только атрибуты, сейчас привязанные к типу.
    """
    bound_ids = {str(b.attribute_id) for b in t.bindings}
    wanted: dict = {}
    for item in values or []:
        aid = str(parse_uuid(str(item.get("attribute_id"))))
        if aid not in bound_ids:
            raise DomainError(
                status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                detail=f"Атрибут {aid} не привязан к типу материала",
            )
        wanted[aid] = item.get("values") or []

    # Удаляем старые значения только по привязанным атрибутам (осиротевшие живут, FR-051)
    orphan_guard = "00000000-0000-0000-0000-000000000000"
    bound_uuids = {parse_uuid(a) for a in bound_ids if parse_uuid(a) is not None}
    for av in db.execute(
        select(models.AttributeValue).where(
            models.AttributeValue.material_id == m.id,
            models.AttributeValue.attribute_id.in_(bound_uuids) if bound_uuids
            else models.AttributeValue.attribute_id.in_([parse_uuid(orphan_guard)]),
        )
    ).scalars().all():
        db.delete(av)

    for aid, vals in wanted.items():
        attr = db.execute(
            select(models.Attribute).where(models.Attribute.id == parse_uuid(aid))
        ).scalar_one()
        vtype = attr.value_type.value if hasattr(attr.value_type, "value") else str(attr.value_type)
        field = _VALUE_FIELDS[vtype]
        items = list(vals)
        if not attr.is_multivalue and len(items) > 1:
            raise DomainError(
                status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                detail=f"Атрибут «{attr.name}» — однозначный",
            )
        for raw in items:
            db.add(models.AttributeValue(
                material_id=m.id, attribute_id=attr.id,
                **{field: _cast(db, vtype, raw, attr)},
            ))


def _cast(db: Session, vtype: str, raw, attr: models.Attribute):
    """Приведение и валидация значения по типу (FR-044; URL — LLD §2.2)."""
    if vtype == "dictionary":
        dv = db.execute(
            select(models.DictionaryValue).where(models.DictionaryValue.id == parse_uuid(str(raw)))
        ).scalar_one_or_none()
        if dv is None or str(dv.dictionary_id) != str(attr.dictionary_id):
            raise DomainError(
                status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                detail="Значение должно быть из справочника атрибута (FR-047)",
            )
        return dv.id
    if vtype == "number":
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise DomainError(
                status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                detail="Ожидалось число",
            )
    if vtype == "date":
        from datetime import datetime

        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            raise DomainError(
                status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                detail="Ожидалась дата ISO 8601",
            )
    if vtype == "url":
        s = str(raw or "")
        if not (s.startswith("http://") or s.startswith("https://")):
            raise DomainError(
                status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                detail="Ожидался URL (http:// или https://)",
            )
        return s
    return str(raw) if raw is not None else None


def missing_required(db: Session, m: models.Material, t: models.MaterialType) -> list[str]:
    """Список имён незаполненных обязательных атрибутов существующего материала (FR-048)."""
    bound = [b.attribute for b in t.bindings]
    if not bound:
        return []
    filled = set(
        db.execute(
            select(models.AttributeValue.attribute_id).where(
                models.AttributeValue.material_id == m.id
            )
        ).scalars()
    )
    return [a.name for a in bound if a.is_required and a.id not in filled]


def missing_required_for_new(db: Session, t: models.MaterialType, supplied: dict) -> list[str]:
    """Обязательные, не покрытые значениями нового материала (FR-048, pre-flush)."""
    return [
        b.attribute.name
        for b in t.bindings
        if b.attribute.is_required
        and not (supplied.get(str(b.attribute_id)) or [])
    ]
