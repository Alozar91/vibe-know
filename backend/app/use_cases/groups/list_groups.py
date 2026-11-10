# Use-case: дерево групп (FR-015; чтение — предикат групп FR-103, этап 4).
# Этап 3: предикат прав ещё не введён — список отдаётся аутентифицированным (уточнение этапа 4).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.groups.dto import to_out, to_tree


def list_groups(
    db: Session, include_deleted: bool = False, only_deleted: bool = False
) -> list[dict]:
    """Дерево групп; удалённые — только СА (US-050, служебный раздел — этап 10)."""
    stmt = select(models.Group).order_by(models.Group.created_at)
    if only_deleted:  # служебный раздел: только удалённые ветки
        stmt = stmt.where(models.Group.is_deleted.is_(True))
    elif not include_deleted:
        stmt = stmt.where(models.Group.is_deleted.is_(False))
    rows = db.execute(stmt).scalars().all()
    if only_deleted:
        # Плоский список (не дерево): родитель удалённого узла может быть жив
        # и не попасть в выборку — дерево потеряло бы узел (US-050)
        return [{**to_out(g), "children": []} for g in rows]
    return to_tree(list(rows))
