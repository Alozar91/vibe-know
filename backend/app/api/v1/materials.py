# Materials — транспорт (LLD §12.3). Логика: use_cases/materials/*.
# If-Match на мутациях (FR-095); ETag в ответе = "<version>" (LLD §12.1).
import uuid

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
    per_page: int | None = None,
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
    from sqlalchemy import select

    from app.db import models
    from app.use_cases.common import require_super

    require_super(user.is_super)
    rows = db.execute(
        select(models.Material)
        .where(models.Material.is_deleted.is_(True))
        .order_by(models.Material.deleted_at.desc())
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
    from app.use_cases.lifecycle.audit import audit_log
    from app.use_cases.materials.create_material import create_material

    out = create_material(
        db, user, body.group_id, body.name, body.type_id,
        text_content=body.text_content,
        attribute_values=body.attribute_values, tag_ids=body.tag_ids,
    )
    # US-049 ш.1 (FR-140): создание — в журнале
    audit_log(db, user, "material.create", "material",
              uuid.UUID(out["id"]))
    db.commit()
    return out


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

    from app.use_cases.lifecycle.audit import audit_log
    from app.use_cases.materials.delete_material import delete_material

    result = delete_material(db, user, material_id, if_match)
    # US-049 ш.1 (FR-140): удаление — в журнале
    audit_log(db, user, "material.delete", "material", uuid.UUID(result["id"]),
              details={"version": result["version"]})
    db.commit()
    return Response(status_code=204, headers={"ETag": f'"{result["version"]}"'})


# ==========================================================================
# Этап 7: мастер-подчинённый (LLD §12.3; US-024–028, US-038)
# ==========================================================================

class ChildIn(BaseModel):
    kind: str  # adaptation | translation (FR-034)
    group_id: str
    name: str | None = Field(default=None, min_length=1)
    language_id: str | None = None  # для kind=translation (16.1-115)


class MasterIn(BaseModel):
    master_id: str


class MoveIn(BaseModel):
    group_id: str


class CopyIn(BaseModel):
    group_id: str


class CommentIn(BaseModel):
    text: str = Field(min_length=1)


@router.post("/materials/{material_id}/children", status_code=201)
async def create_child_ep(
    user: CurrentUserDep, material_id: str, body: ChildIn,
    db: Session = Depends(get_db),
) -> dict:
    """Создание подчинённого — адаптация/перевод (FR-033–035; US-024/025)."""
    from app.use_cases.materials.create_child import create_child_material

    return create_child_material(
        db, user, material_id, body.kind, body.group_id,
        name=body.name, language_id=body.language_id,
    )


@router.post("/materials/{material_id}/master")
async def change_master_ep(
    user: CurrentUserDep, material_id: str, body: MasterIn,
    db: Session = Depends(get_db),
) -> dict:
    """Смена мастера (FR-032/036; US-026); уведомление не создаётся (16.1-111)."""
    from app.use_cases.materials.master_change import change_master

    return change_master(db, user, material_id, body.master_id)


@router.delete("/materials/{material_id}/master")
async def detach_master_ep(
    user: CurrentUserDep, material_id: str, db: Session = Depends(get_db),
) -> dict:
    """Отвязка от мастера (FR-036; US-026 п.5); 16.1-111 — без события."""
    from app.use_cases.materials.master_change import detach_master

    return detach_master(db, user, material_id)


@router.post("/materials/{material_id}/move")
async def move_material_ep(
    user: CurrentUserDep, material_id: str, body: MoveIn,
    db: Session = Depends(get_db),
) -> dict:
    """Перемещение между группами (FR-037; US-027); конфликт имени — 409."""
    from app.use_cases.materials.move_material import move_material

    return move_material(db, user, material_id, body.group_id)


@router.post("/materials/{material_id}/copy", status_code=201)
async def copy_material_ep(
    user: CurrentUserDep, material_id: str, body: CopyIn,
    db: Session = Depends(get_db),
) -> dict:
    """Копирование (FR-092, 7.10; US-028) — черновик «<имя> Копия»."""
    from app.use_cases.materials.copy_material import copy_material

    return copy_material(db, user, material_id, body.group_id)


@router.get("/materials/{material_id}/comments")
async def list_comments_ep(
    user: CurrentUserDep, material_id: str, db: Session = Depends(get_db),
) -> dict:
    """Комментарии (FR-096/097; US-038): чтение — видимость материала."""
    from app.use_cases.materials.comments import list_comments

    return list_comments(db, user, material_id)


@router.post("/materials/{material_id}/comments", status_code=201)
async def add_comment_ep(
    user: CurrentUserDep, material_id: str, body: CommentIn,
    db: Session = Depends(get_db),
) -> dict:
    """Новый комментарий (FR-098; US-038): участники процесса; аудит."""
    from app.use_cases.materials.comments import add_comment

    return add_comment(db, user, material_id, body.text)
