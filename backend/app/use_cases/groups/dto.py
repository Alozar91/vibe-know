# DTO групп — общие для сценариев ресурса.
from app.db import models


def to_out(g: models.Group) -> dict:
    return {
        "id": str(g.id),
        "name": g.name,
        "parent_id": str(g.parent_id) if g.parent_id else None,
        "path": g.path,
        "is_deleted": g.is_deleted,
    }


def to_tree(nodes: list[models.Group], deleted: bool = False) -> list[dict]:
    """Дерево из плоского списка (path — материализованный путь, сортировка по имени)."""
    by_parent: dict[str | None, list[models.Group]] = {}
    for g in nodes:
        key = str(g.parent_id) if g.parent_id else None
        by_parent.setdefault(key, []).append(g)
    for v in by_parent.values():
        v.sort(key=lambda x: x.name.lower())

    def build(parent_key: str | None) -> list[dict]:
        out = []
        for g in by_parent.get(parent_key, []):
            item = to_out(g)
            item["children"] = build(str(g.id))
            out.append(item)
        return out

    return build(None)
