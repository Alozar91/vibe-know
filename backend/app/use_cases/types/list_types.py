# Use-case: список типов материалов (FR-043) — аутентифицированным (нужно для карточки).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.types.dto import to_out


def list_types(db: Session) -> list[dict]:
    rows = db.execute(select(models.MaterialType).order_by(models.MaterialType.name)).scalars().all()
    return [to_out(t) for t in rows]
