# Роутер /api/v1 (LLD §12.3). Ресурсы этапов 2–10 подключаются здесь по мере реализации.
from fastapi import APIRouter

api_router = APIRouter()

# --- Демо-заглушка этапа 1: удаляется на этапе 2 вместе с auth-модулем ---
_DEMO_MATERIALS = [
    {"id": 1, "title": "Тестовый материал"},
]


@api_router.get("/me", tags=["me"])
async def me():
    """Профиль из токена (FR-151). На этапе 1 — заглушка, аутентификация — этап 2."""
    return {"display_name": "Аноним", "stage": 1}


@api_router.get("/materials", tags=["materials"])
async def list_materials():
    """Заглушка для проверки конвейера nginx → api на этапе 1 (реализация — этап 4)."""
    return {"items": _DEMO_MATERIALS, "total": len(_DEMO_MATERIALS), "page": 1, "per_page": 50}
# --- конец заглушки ---
