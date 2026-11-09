# Materials — транспорт (LLD §12.3). Логика: use_cases/materials/*.
# If-Match на мутациях (FR-095); ETag в ответе = "<version>" (LLD §12.1).
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db

router = APIRouter(tags=["materials"])


class MaterialIn(BaseModel):
    name: str = Field(min_length=1)  # NAME_TOO_LONG — в use-case (FR-027)
    group_id: str
    type_id: str
    text_content: str | None = None
    attribute_values: list[dict] = Field(default_factory=list)
    tag_ids: list[str] = Field(default_factory=list)


class MaterialPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    type_id: str | None = None
    text_content: str | None = None
    attribute_values: list[dict] | None = None
    tag_ids: list[str] | None = None


@router.get("/materials")
async def list_materials_ep(
    user: CurrentUserDep,
    db: Session = Depends(get_db),
    group_id: str | None = None,
    include_subgroups: bool = True,
    type_id: str | None = None,
    status: str | None = None,
    author_id: str | None = None,
    include_archive: bool = False,
    sort: str = "updated_at",
    order: str = "desc",
    page: int = 1,
    per_page: int = 50,
    section: str | None = None,
) -> dict:
    """Список с фильтрами/сортировкой/пагинацией (FR-112/115–117/121; US-005/006)."""
    from app.use_cases.materials.list_materials import list_materials

    return list_materials(
        db, user, group_id=group_id, include_subgroups=include_subgroups,
        type_id=type_id, status=status, author_id=author_id,
        include_archive=include_archive, sort=sort, order=order,
        page=page, per_page=per_page, section=section,
    )


@router.get("/materials/deleted")
async def deleted_materials_ep(user: CurrentUserDep, db: Session = Depends(get_db)) -> dict:
    """Служебный раздел (FR-090) — только СА; полная реализация — этап 10."""
    from app.use_cases.common import require_super
    from sqlalchemy import select

    require_super(user.is_super)
    rows = db.execute(
        select(__import__("app.db.models", fromlist=["Material"]).Material)
        .where(__import__("app.db.models", fromlist=["Material"]).Material.is_deleted.is_(True))
        .order_by(__import__("app.db.models", fromlist=["Material"]).Material.deleted_at.desc())
    ).scalars().all()
    return {
        "items": [
            {"id": str(m.id), "name": m.name,
             "deleted_at": m.deleted_at.isoformat() if m.deleted_at else None}
            for m in rows
        ],
        "total": len(rows), "page": 1, "per_page": len(rows) or 1,
    }


@router.post("/materials", status_code=201)
async def create_material_ep(user: CurrentUserDep, body: MaterialIn, db: Session = Depends(get_db)) -> dict:
    """Создание (в т.ч. пустышка) — право create в группе (FR-024–026)."""
    from app.use_cases.materials.create_material import create_material

    return create_material(
        db, user, body.group_id, body.name, body.type_id,
        text_content=body.text_content,
        attribute_values=body.attribute_values, tag_ids=body.tag_ids,
    )


@router.get("/materials/{material_id}")
async def get_material_ep(
    user: CurrentUserDep, material_id: str, db: Session = Depends(get_db)
):
    """Карточка (US-037): поля + атрибуты/теги + права (FR-129); ETag = версия."""
    from fastapi import Response

    from app.use_cases.materials.get_material import get_material

    out = get_material(db, user, material_id)
    return Response(
        content=json_dumps(out), media_type="application/json",
        headers={"ETag": f'"{out["version"]}"'},
    )


@router.patch("/materials/{material_id}")
async def update_material_ep(
    user: CurrentUserDep, material_id: str, body: MaterialPatch,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
):
    """Правка (If-Match обязателен — FR-095); ETag в ответе = новая версия."""
    from fastapi import Response

    from app.use_cases.materials.update_material import update_material

    result = update_material(
        db, user, material_id, if_match,
        name=body.name, type_id=body.type_id, text_content=body.text_content,
        attribute_values=body.attribute_values, tag_ids=body.tag_ids,
    )
    return Response(
        content=json_dumps(result), media_type="application/json",
        headers={"ETag": f'"{result["version"]}"'},
    )


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


@router.delete("/materials/{material_id}")
async def delete_material_ep(
    user: CurrentUserDep, material_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
):
    """Soft-delete (FR-090): только draft/in_review; право delete; 204 + ETag."""
    from fastapi import Response

    from app.use_cases.materials.delete_material import delete_material

    result = delete_material(db, user, material_id, if_match)
    return Response(status_code=204, headers={"ETag": f'"{result["version"]}"'})
