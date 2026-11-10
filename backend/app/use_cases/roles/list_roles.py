# Use-case: список шаблонов ролей (FR-008, US-043 шаг 1).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.roles.dto import to_out


def list_roles(db: Session) -> list[dict]:
    """Базовые шаблоны + клоны + виртуальная «Все пользователи» (FR-009)."""
    rows = db.execute(select(models.Role).order_by(models.Role.created_at)).scalars().all()
    return [to_out(r) for r in rows]
