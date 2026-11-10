# Роутер /api/v1 (LLD §12.3). Ресурсы подключаются по мере реализации этапов.
from fastapi import APIRouter

from app.api.v1 import (
    admin,
    attributes,
    dictionaries,
    files,
    groups,
    lifecycle,
    materials,
    me,
    notifications,
    permissions,
    rag,
    roles,
    search,
    tags,
    types,
    user_roles,
    users,
    versions,
)

api_router = APIRouter()
api_router.include_router(me.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(user_roles.router)
api_router.include_router(groups.router)
api_router.include_router(types.router)
api_router.include_router(attributes.router)
api_router.include_router(dictionaries.router)
api_router.include_router(tags.router)
api_router.include_router(materials.router)
api_router.include_router(files.router)
api_router.include_router(versions.router)
api_router.include_router(permissions.materials_router)
api_router.include_router(permissions.groups_router)
api_router.include_router(permissions.snapshot_router)
api_router.include_router(lifecycle.router)
api_router.include_router(lifecycle.rules_router)
api_router.include_router(search.router)
api_router.include_router(notifications.router)
api_router.include_router(notifications.router_triggers)
api_router.include_router(admin.router)
api_router.include_router(rag.router)

# Дальше: этап 11 (НФТ/приёмка).
