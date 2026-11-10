# Use-case: список атрибутов глобального пула (FR-044).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.attributes.dto import to_out


def list_attributes(db: Session) -> list[dict]:
    rows = db.execute(
        select(models.Attribute).order_by(models.Attribute.display_order, models.Attribute.name)
    ).scalars().all()
    return [to_out(a) for a in rows]
