# Точка входа API: app factory (HLD §7, LLD §12).
# Этап 1: каркас — healthz, /metrics, конвенции ошибок; ресурсы добавляются по этапам 2–10.
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.api.health import router as health_router
from app.api.v1.router import api_router

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

    # REST API /api/v1 (FR-130)
    app.include_router(api_router, prefix="/api/v1")

    # healthz/readyz — вне версионированного префикса (для healthcheck Compose)
    app.include_router(health_router)

    # Prometheus /metrics (NFR-019; экспозер ASGI, внутренняя сеть — LLD §12.3)
    app.mount("/metrics", make_asgi_app())

    return app


async def _lifespan(app: FastAPI):
    log.info("api.started")
    yield
    log.info("api.stopped")


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
        # Бизнес-ошибки use-cases → problem+json с кодом LLD §12.2
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
        return problem(
            400,
            "VALIDATION_ERROR",
            "Ошибка валидации запроса",
            "Проверьте формат и значения полей запроса",
            params={"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.error("api.unhandled_error", error=str(exc), path=request.url.path)
        return problem(500, "INTERNAL", "Внутренняя ошибка сервера", "Обратитесь к системному администратору")


async def _log_4xx(request, exc):
    log.info("api.validation_error", path=request.url.path)


app = create_app()
