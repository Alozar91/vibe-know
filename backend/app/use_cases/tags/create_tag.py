# Use-case: создание тега (FR-052, US-033 шаг 2) — только СА; свободное создание
# пользователями запрещено (US-031 шаг 4 — только выбор с автодополнением).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import require_super
from app.use_cases.errors import DomainError, name_conflict


def create_tag(db: Session, is_super: bool, name: str) -> dict:
    require_super(is_super)
    if not name or not name.strip():
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Название тега обязательно")
    dup = db.execute(select(models.Tag).where(models.Tag.name == name.strip())).scalar_one_or_none()
    if dup:
        raise name_conflict("Тег с таким названием уже существует")
    t = models.Tag(name=name.strip())
    db.add(t)
    db.commit()
    return {"id": str(t.id), "name": t.name}
