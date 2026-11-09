# DTO справочников.
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import models


def to_out(d: models.Dictionary) -> dict:
    # values — строками (FR-047); value_items — с id (для карточки: значения
    # справочника в атрибутах резолвятся в текст, US-031/FR-049)
    return {
        "id": str(d.id),
        "name": d.name,
        "values": [v.value for v in d.values],
        "value_items": [{"id": str(v.id), "value": v.value} for v in d.values],
    }
