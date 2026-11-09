# Use-case: список тегов словаря (FR-052) — аутентифицированным (автодополнение US-031).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


def list_tags(db: Session, q: str | None = None) -> list[dict]:
    """Словарь тегов; q — префиксный фильтр для автодополнения."""
    stmt = select(models.Tag).order_by(models.Tag.name)
    if q:
        stmt = stmt.where(models.Tag.name.ilike(f"{q}%"))
    rows = db.execute(stmt).scalars().all()
    return [{"id": str(t.id), "name": t.name} for t in rows]
