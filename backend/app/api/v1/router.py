# Роутер /api/v1 (LLD §12.3). Ресурсы подключаются по мере реализации этапов.
from fastapi import APIRouter

from app.api.v1 import (
    attributes,
    dictionaries,
    groups,
    me,
    roles,
    tags,
    types,
    user_roles,
    users,
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

# Дальше по этапам: materials (4), lifecycle (5), files (6),
# master-detail (7), search (8), notifications (9), admin/audit/settings (10).
