# Health-эндпоинты (этап 1).
# /healthz — живость api (для healthcheck Compose); /readyz — готовность (зависимости).
import enum

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class ComponentState(str, enum.Enum):
    up = "up"
    down = "down"


class Component(BaseModel):
    state: ComponentState
    detail: str | None = None


class HealthResponse(BaseModel):
    status: ComponentState
    components: dict[str, Component]


@router.get("/healthz")
def healthz() -> dict:
    """Живость: процесс отвечает (без обращения к зависимостям)."""
    return {"status": "ok"}


@router.get("/readyz", response_model=HealthResponse)
async def readyz() -> HealthResponse:
    """Готовность: PostgreSQL, Valkey, Keycloak, silo — этап 1: базовая проверка PG/Valkey."""
    components: dict[str, Component] = {}
    status = ComponentState.up

    try:
        from sqlalchemy import text

        from app.db.engine import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        components["postgres"] = Component(state=ComponentState.up)
    except Exception as e:  # pragma: no cover - зависит от окружения
        components["postgres"] = Component(state=ComponentState.down, detail=str(e))
        status = ComponentState.down

    try:
        import redis.asyncio as aredis

        from app.config import get_settings

        r = aredis.from_url(get_settings().redis_url, socket_connect_timeout=1)
        await r.ping()
        await r.aclose()
        components["valkey"] = Component(state=ComponentState.up)
    except Exception as e:  # pragma: no cover
        components["valkey"] = Component(state=ComponentState.down, detail=str(e))
        status = ComponentState.down

    # Keycloak и silo добавляются на этапах 2 и 6 соответственно.

    return HealthResponse(status=status, components=components)
