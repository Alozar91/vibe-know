# Версии — транспорт (LLD §12.3, §5.2; FR-145–148). Логика: use_cases/materials/versions.py.
from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db import models
from app.db.engine import get_db
from app.use_cases.common import parse_uuid

router = APIRouter(tags=["versions"])


@router.get("/materials/{material_id}/versions")
def list_versions_ep(
    user: CurrentUserDep, material_id: str, db: Session = Depends(get_db)
) -> dict:
    """Список версий (US-041 шаг 1, FR-145): даты/авторы; видимость = видимость
    материала; доступно и для архивных."""
    from app.use_cases.materials.get_material import get_material_or_404

    m = get_material_or_404(db, user, material_id)  # видимость материала
    rows = db.execute(
        select(models.MaterialVersion)
        .where(models.MaterialVersion.material_id == m.id)
        .order_by(models.MaterialVersion.number.desc())
    ).scalars().all()
    return {
        "items": [
            {
                "number": v.number,
                "author_id": str(v.author_id),
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in rows
        ],
        "total": len(rows), "page": 1, "per_page": len(rows) or 1,
    }


@router.get("/materials/{material_id}/versions/{number}")
def get_version_ep(
    user: CurrentUserDep, material_id: str, number: int, db: Session = Depends(get_db)
) -> dict:
    """Версия целиком (US-041 шаг 4): прежние файл/текст/название/тип/атрибуты/теги."""
    from app.use_cases.materials.get_material import get_material_or_404
    from app.use_cases.materials.versions import get_version_or_404

    m = get_material_or_404(db, user, material_id)
    v = get_version_or_404(db, m.id, number)
    snap = v.snapshot or {}
    return {
        "number": v.number,
        "author_id": str(v.author_id),
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "snapshot": snap,
    }


@router.get("/materials/{material_id}/versions/{number}/diff")
def diff_version_ep(
    user: CurrentUserDep, material_id: str, number: int, db: Session = Depends(get_db)
) -> dict:
    """Diff соседних версий (§5.2, FR-146, 16.1-83): сравнение версии n с n−1.
    Текст — построчный unified-diff; метаданные — {поле, старое, новое}; файл — file_changed."""
    import difflib

    from app.use_cases.materials.get_material import get_material_or_404
    from app.use_cases.materials.versions import get_version_or_404

    m = get_material_or_404(db, user, material_id)
    v = get_version_or_404(db, m.id, number)
    if number <= 1:
        # первая версия — сравнение с «пустым» состоянием (всё добавлено)
        prev = {"file_id": None, "text": None, "name": "", "type_id": "",
                "attributes": [], "tags": []}
    else:
        p = get_version_or_404(db, m.id, number - 1)
        prev = p.snapshot or {}

    cur = v.snapshot or {}
    file_changed = (cur.get("file_id") or None) != (prev.get("file_id") or None)

    # Текст — построчный унифицированный diff
    text_diff = []
    old_t = (prev.get("text") or "").splitlines(keepends=True)
    new_t = (cur.get("text") or "").splitlines(keepends=True)
    if old_t or new_t:
        for line in difflib.unified_diff(old_t, new_t, lineterm=""):
            text_diff.append(line)

    # Метаданные — {поле, старое, новое}
    meta = []
    if cur.get("name") != prev.get("name"):
        meta.append({"field": "name", "old": prev.get("name") or "", "new": cur.get("name") or ""})
    if cur.get("type_id") != prev.get("type_id"):
        old_type = _type_name(db, prev.get("type_id"))
        new_type = _type_name(db, cur.get("type_id"))
        meta.append({"field": "type", "old": old_type, "new": new_type})
    # атрибуты: сопоставление по attribute_id
    old_attrs = {a["attribute_id"]: a.get("values") or [] for a in (prev.get("attributes") or [])}
    new_attrs = {a["attribute_id"]: a.get("values") or [] for a in (cur.get("attributes") or [])}
    for aid in sorted(set(old_attrs) | set(new_attrs)):
        if old_attrs.get(aid) != new_attrs.get(aid):
            meta.append({
                "field": f"attribute:{aid}",
                "old": ", ".join(str(x) for x in (old_attrs.get(aid) or [])),
                "new": ", ".join(str(x) for x in (new_attrs.get(aid) or [])),
            })
    old_tags = sorted(str(t) for t in (prev.get("tags") or []))
    new_tags = sorted(str(t) for t in (cur.get("tags") or []))
    if old_tags != new_tags:
        meta.append({"field": "tags", "old": ", ".join(old_tags), "new": ", ".join(new_tags)})

    return {
        "number": v.number,
        "file_changed": file_changed,
        "text_diff": text_diff,
        "metadata_changes": meta,
    }


def _type_name(db: Session, type_id: str | None) -> str:
    if not type_id:
        return ""
    t = db.execute(
        select(models.MaterialType).where(models.MaterialType.id == parse_uuid(str(type_id)))
    ).scalar_one_or_none()
    return t.name if t else (type_id or "")


class RestoreIn(BaseModel):
    pass  # тело не требуется; зарезервировано


@router.post("/materials/{material_id}/versions/{number}/restore", status_code=200)
def restore_version_ep(
    user: CurrentUserDep, material_id: str, number: int,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> dict:
    """Восстановление версии (§5.2, FR-148, US-042): снапшот применяется как
    правка контента по правилам §4.2; новая версия; master_id не меняется."""
    from app.use_cases.materials.versions_restore import restore_version

    result = restore_version(db, user, material_id, number, if_match)
    return _json(result, headers={"ETag": f'"{result["version"]}"'})


def _json(obj, headers=None):
    import json

    return Response(
        content=json.dumps(obj, ensure_ascii=False), media_type="application/json",
        headers=headers or {},
    )
