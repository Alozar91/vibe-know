# Точка входа API: app factory (HLD §7, LLD §12).
# Этап 1: каркас — healthz, /metrics, конвенции ошибок; ресурсы добавляются по этапам 2–10.
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.api.health import router as health_router
from app.api.v1.router import api_router
from contextlib import AsyncExitStack, asynccontextmanager

log = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        openapi_url="/api/v1/openapi.json",  # NFR-021, LLD §12.1
        docs_url="/api/v1/docs",
        lifespan=_lifespan,
    )

    # Веб-клиент ходит через nginx (один origin на проде); CORS — для dev-режима Vite
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url, "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Конвенции ошибок RFC 7807 + доменные коды (LLD §12.1/12.2)
    register_exception_handlers(app)

    # Метрики API: запросы/латентность/5xx (NFR-019, HLD §8.3) — до маршрутов
    register_metrics_middleware(app)

    # REST API /api/v1 (FR-130)
    app.include_router(api_router, prefix="/api/v1")

    # MCP-сервер (пост-MVP шаг [7] ч.5, RAG_DESIGN §8-5, CONCEPT 10.4):
    # read-only тулы kb_search/kb_groups поверх /rag/retrieve; аутентификация
    # та же (Bearer + introspection). Отключается пустым KB_MCP_ENABLED.
    if settings.mcp_enabled:
        from app.api.mcp_server import mcp_asgi_app, mcp_lifespan

        app.mount("/api/v1/mcp", mcp_asgi_app())
        _wrap_lifespan_with_mcp(app, mcp_lifespan)

    # healthz/readyz — вне версионированного префикса (для healthcheck Compose)
    app.include_router(health_router)

    # Prometheus /metrics (NFR-019; экспозер ASGI, внутренняя сеть — LLD §12.3)
    app.mount("/metrics", make_asgi_app())

    return app


async def _lifespan(app: FastAPI):
    # Кэш прав: LISTEN rights_invalidate в фоновом потоке (§3.3, [уточнение LLD])
    from app.use_cases.permissions.cache import start_listener

    start_listener()
    log.info("api.started")
    yield
    log.info("api.stopped")


def _wrap_lifespan_with_mcp(app: FastAPI, mcp_lifespan) -> None:
    """Хост владеет lifespan MCP-сессии (Mount гасит собственный — docs SDK).

    Сессия MCP стартует после LISTEN-потока кэша прав; её сбой валит запуск
    (честный отказ вместо тишины).
    """
    from contextlib import asynccontextmanager as _alcm

    original = app.router.lifespan_context

    @_alcm
    async def combined(app_: FastAPI):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(original(app_))
            await stack.enter_async_context(mcp_lifespan(app_))
            yield

    app.router.lifespan_context = combined


def register_exception_handlers(app: FastAPI) -> None:
    from fastapi.exceptions import RequestValidationError
    from fastapi import Request, HTTPException
    from fastapi.responses import JSONResponse

    from app.use_cases.errors import DomainError

    def problem(
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        params: dict | None = None,
    ) -> JSONResponse:
        # RFC 7807 + доменный code (LLD §12.1); title/detail — на русском (NFR-018)
        return JSONResponse(
            status_code=status,
            media_type="application/problem+json",
            content={
                "type": f"https://kb.example.local/errors/{code}",
                "title": title,
                "status": status,
                "detail": detail,
                "code": code,
                **({"params": params} if params else {}),
            },
        )

    @app.exception_handler(DomainError)
    async def domain_handler(request: Request, exc: DomainError):
        # Бизнес-ошибки use-cases → problem+json с кодом LLD §12.2;
        # откат недозакоммиченной транзакции запроса (частичное состояние не живёт)
        from app.db.engine import get_db as _get_db

        session = getattr(request.state, "db_session", None)
        if session is not None:
            session.rollback()
        return problem(exc.status, exc.code, exc.title, exc.detail, exc.params)

    @app.exception_handler(HTTPException)
    async def http_handler(request: Request, exc: HTTPException):
        # Ошибки фреймворка (404 маршрута, 405 и т.п.) — тоже problem+json (LLD §12.1)
        return problem(
            exc.status_code,
            "HTTP_ERROR" if exc.status_code < 500 else "INTERNAL",
            "Ошибка запроса" if exc.status_code < 500 else "Внутренняя ошибка сервера",
            exc.detail if isinstance(exc.detail, str) else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        await _log_4xx(request, exc)
        # exc.errors() может содержать input с bytes — не JSON-сериализуемо (500).
        # Оставляем только безопасные поля каждой ошибки (NFR: единый problem+json).
        safe = [
            {k: v for k, v in err.items() if k != "input"} for err in exc.errors()
        ]
        return problem(
            400,
            "VALIDATION_ERROR",
            "Ошибка валидации запроса",
            "Проверьте формат и значения полей запроса",
            params={"errors": safe},
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.error("api.unhandled_error", error=str(exc), path=request.url.path)
        return problem(500, "INTERNAL", "Внутренняя ошибка сервера", "Обратитесь к системному администратору")


async def _log_4xx(request, exc):
    log.info("api.validation_error", path=request.url.path)


def register_metrics_middleware(app: FastAPI) -> None:
    """HTTP-метрики на каждый запрос (NFR-019): счётчик, латентность, in-progress.

    Шаблон маршрута (path) вместо фактического URL — чтобы не плодить серии на
    каждый id материала/группы (cardinality). Нормализация: uuid/цифры → {id}.
    """
    import re
    import time

    from fastapi import Request, Response

    from app.api.metrics import IN_PROGRESS, observe

    _uuid_re = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    _digits_re = re.compile(r"^\d+$")

    def _norm(seg: str) -> str:
        if _uuid_re.match(seg) or _digits_re.match(seg):
            return "{id}"
        return seg

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next) -> Response:
        method = request.method
        IN_PROGRESS.labels(method=method).inc()
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            status = 500
            raise
        finally:
            elapsed = time.perf_counter() - start
            IN_PROGRESS.labels(method=method).dec()
            # Нормализуем path сегментами (быстрее, чем разбор route-объектов)
            raw_path = request.scope.get("path", "")
            norm = "/".join(_norm(s) for s in raw_path.split("/") if s != "")
            norm = "/" + norm if norm else raw_path
            # /metrics и health-пробы не считаем (самоскрейп искажает картину)
            if norm not in ("/metrics", "/healthz", "/readyz"):
                observe(method, norm, status, elapsed)
        return response



app = create_app()
