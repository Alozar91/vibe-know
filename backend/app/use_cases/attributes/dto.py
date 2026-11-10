# DTO атрибутов.
from app.db import models

VALUE_TYPES = ("string", "number", "date", "url", "dictionary")  # FR-044
MULTIVALUE_ALLOWED = ("string", "url", "dictionary")  # FR-044: только для этих типов


def to_out(a: models.Attribute) -> dict:
    return {
        "id": str(a.id),
        "name": a.name,
        "value_type": a.value_type.value if hasattr(a.value_type, "value") else str(a.value_type),
        "is_multivalue": a.is_multivalue,
        "is_required": a.is_required,
        "display_order": a.display_order,
        "dictionary_id": str(a.dictionary_id) if a.dictionary_id else None,
    }
