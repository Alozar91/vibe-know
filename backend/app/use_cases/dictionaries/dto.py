# DTO справочников.
from app.db import models


def to_out(d: models.Dictionary) -> dict:
    return {
        "id": str(d.id),
        "name": d.name,
        "values": [v.value for v in d.values],
    }
