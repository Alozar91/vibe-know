# DTO типов — общие для сценариев ресурса.
from app.db import models


def to_out(t: models.MaterialType) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "attributes": [
            {
                "id": str(b.attribute.id),
                "name": b.attribute.name,
                "value_type": str(b.attribute.value_type),
                "is_multivalue": b.attribute.is_multivalue,
                "is_required": b.attribute.is_required,
                "display_order": b.attribute.display_order,
                # dictionary-атрибуты: фронт по dictionary_id подтягивает
                # значения справочника (GET /dictionaries) для select'а
                "dictionary_id": str(b.attribute.dictionary_id) if b.attribute.dictionary_id else None,
            }
            for b in sorted(t.bindings, key=lambda x: x.attribute.display_order)
        ],
    }
