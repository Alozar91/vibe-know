# Permissions — транспорт снапшотов прав (LLD §12.3, US-044). Логика: use_cases/permissions/snapshots.
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db

router = APIRouter(tags=["permissions"])


class EntryIn(BaseModel):
    permission: str
    state: str  # allow | deny | unset


class SnapshotIn(BaseModel):
    role_id: str | None = None  # None → «Все пользователи» (FR-009)
    entries: list[EntryIn] = Field(default_factory=list)


def _object_router(object_type: str, prefix: str, tag: str) -> APIRouter:
    """Эндпоинты /{materials|groups}/{id}/permissions (LLD §12.3: «аналогично для групп»)."""
    r = APIRouter(tags=[tag])

    @r.get(f"/{prefix}/{{object_id}}/permissions")
    async def list_ep(object_id: str, user: CurrentUserDep, db: Session = Depends(get_db)) -> list[dict]:
        from app.use_cases.permissions.snapshots import list_snapshots

        return list_snapshots(db, user.is_super, object_type, object_id)

    @r.post(f"/{prefix}/{{object_id}}/permissions", status_code=201)
    async def create_ep(object_id: str, body: SnapshotIn, user: CurrentUserDep, db: Session = Depends(get_db)) -> dict:
        from app.use_cases.permissions.snapshots import create_snapshot

        return create_snapshot(
            db, user.is_super, user.user_id, object_type, object_id,
            body.role_id, [e.model_dump() for e in body.entries], actor=user,
        )

    return r


# PATCH/DELETE снапшота — общие (id снапшота уникален глобально)
snapshot_router = APIRouter(tags=["permissions"])


class SnapshotPatch(BaseModel):
    entries: list[EntryIn]


@snapshot_router.patch("/permissions/snapshots/{snapshot_id}")
async def patch_snapshot_ep(snapshot_id: str, body: SnapshotPatch, user: CurrentUserDep, db: Session = Depends(get_db)) -> dict:
    from app.use_cases.permissions.snapshots import update_snapshot

    return update_snapshot(db, user.is_super, snapshot_id, [e.model_dump() for e in body.entries], actor=user)


@snapshot_router.delete("/permissions/snapshots/{snapshot_id}", status_code=204)
async def delete_snapshot_ep(snapshot_id: str, user: CurrentUserDep, db: Session = Depends(get_db)) -> None:
    from app.use_cases.permissions.snapshots import delete_snapshot

    delete_snapshot(db, user.is_super, snapshot_id, actor=user)


# Подключение: /materials/{id}/permissions, /groups/{id}/permissions
materials_router = _object_router("material", "materials", "permissions")
groups_router = _object_router("group", "groups", "permissions")
