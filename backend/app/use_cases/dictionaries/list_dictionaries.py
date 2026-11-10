# Use-case: список справочников (FR-047) — аутентифицированным (нужно для карточки).
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import models
from app.use_cases.dictionaries.dto import to_out


def list_dictionaries(db: Session) -> list[dict]:
    rows = db.execute(
        select(models.Dictionary).options(selectinload(models.Dictionary.values))
        .order_by(models.Dictionary.name)
    ).scalars().all()
    return [to_out(d) for d in rows]
