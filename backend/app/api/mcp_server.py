# MCP-сервер (пост-MVP шаг [7] ч.5, RAG_DESIGN §8-5) — read-only поверх
# POST /rag/retrieve (CONCEPT 10.4): ИИ-агенты читают базу знаний под правами
# реального пользователя. REST — основной интерфейс (§7.1-2); MCP — обёртка:
# те же use-cases, те же права (предикат §3.2), те же лимиты (k ≤ 20, §9-5).
#
# Аутентификация: Bearer-токен Keycloak → introspection (та же, что у REST,
# LLD §10) → provisioning → CurrentUser в contextvar; тулы читают его через
# get_current_principal(). Read-only: никаких мутаций — только поиск и группы.
#
# Монтирование: FastAPI mount /api/v1/mcp (stateless, JSON-ответы — просто
# интеграция для клиентов без SSE-сессий). Host/Origin-защита транспорта
# отключена: nginx контролирует Host; от подбора токен защищает introspection.
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from app.logging import get_logger

log = get_logger(__name__)

# CurrentUser текущего MCP-запроса (заполняет токен-верификатор, читают тулы)
_principal_var: ContextVar[Any] = ContextVar("kb_mcp_principal", default=None)

_mcp_server: MCPServer | None = None

MCP_INSTRUCTIONS = (
    "Инструменты чтения корпоративной базы знаний. kb_search — семантический "
    "поиск по материалам (векторный или гибридный RRF), kb_groups — дерево "
    "групп для фильтра по группе. Выдача ограничена правами учётной записи, "
    "под которой подключён агент."
)


def get_current_principal() -> Any:
    """CurrentUser вызывающего агента (None — вне MCP-запроса)."""
    return _principal_var.get()


def get_session_factory():
    """Фабрика сессий БД для тулов (обёртка — точка подмены в тестах)."""
    from app.db.engine import get_session_factory as _g

    return _g()


class _KeycloakTokenVerifier(TokenVerifier):
    """Bearer → introspection Keycloak (LLD §10) → CurrentUser в contextvar.

    Схема SDK: verify_token вызывается на каждый HTTP-запрос; возвращённый
    AccessToken попадает в контекст; тулы берут principal через
    get_current_principal(). None → SDK отвечает 401.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        from app.db.engine import get_session_factory

        info: dict[str, Any] | None = None
        try:
            from app.use_cases.users.introspect_token import introspect_token

            info = introspect_token(token)  # fail-closed: сбой → 401 (LLD §10)
        except Exception:
            log.warning("mcp.token_rejected")
            return None
        try:
            from app.use_cases.users.ensure_active import ensure_active
            from app.use_cases.users.get_is_super import is_super
            from app.use_cases.users.provision_user import upsert_user_from_token

            session = get_session_factory()()
            try:
                user = upsert_user_from_token(session, info)
                ensure_active(user)
                session.commit()
                from app.api.deps import CurrentUser

                principal = CurrentUser(user, info, is_super(session, user))
            finally:
                session.close()
        except Exception:
            log.warning("mcp.token_rejected", reason="provisioning_failed")
            return None
        # AccessToken — для SDK; principal — для тулов (contextvar на запрос)
        _principal_var.set(principal)
        return AccessToken(
            token=token,
            client_id=str(info.get("azp") or info.get("client_id") or "kb-mcp"),
            scopes=[],
            expires_at=info.get("exp"),
            subject=info.get("sub"),
            claims=info,
        )


def _kb_search_impl(query: str, k: int = 10, mode: str = "vector",
                    group_id: str | None = None, include_subgroups: bool = True) -> dict[str, Any]:
    """Тело тула kb_search (отдельная функция — переиспользуется тестами)."""
    principal = get_current_principal()
    if principal is None:
        raise MCPError("Требуется аутентификация")
    from app.use_cases.rag.retrieve import log_retrieve_event, retrieve_chunks

    session = get_session_factory()()
    try:
        out = retrieve_chunks(
            session, principal,
            q=query, group_id=group_id,
            include_subgroups=include_subgroups,
            k=k, mode=mode,
        )
        # deep_link как в REST (§7.1-2): /materials/{id}
        for it in out["items"]:
            it["deep_link"] = f"/materials/{it['material']['id']}"
        log_retrieve_event(session, query, out["total"])
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return out


def _kb_groups_impl(limit: int = 100) -> dict[str, Any]:
    """Тело тула kb_groups (отдельная функция — переиспользуется тестами)."""
    principal = get_current_principal()
    if principal is None:
        raise MCPError("Требуется аутентификация")
    from app.use_cases.groups.list_groups import list_groups

    session = get_session_factory()()
    try:
        tree = list_groups(session)
    finally:
        session.close()
    flat: list[dict[str, Any]] = []

    def walk(nodes: list[dict[str, Any]]) -> None:
        for n in nodes:
            flat.append({"id": n["id"], "name": n["name"], "path": n["path"]})
            if n.get("children"):
                walk(n["children"])

    walk(tree)
    return {"groups": flat[: max(1, min(int(limit), 500))], "total": len(flat)}


def _build_server() -> MCPServer:
    from pydantic import AnyHttpUrl

    from app.config import get_settings

    s = get_settings()
    issuer = s.oidc_issuer.rstrip("/") + "/"
    # resource_server_url — публичный адрес эндпоинта; на стенде MCP доступен
    # по тому же origin, что и REST (nginx /api/). Отражаем фактический origin.
    public = s.frontend_url.rstrip("/")
    resource_url = f"{public}/api/v1/mcp"

    verifier = _KeycloakTokenVerifier()
    server = MCPServer(
        "kb-knowledge",
        instructions=MCP_INSTRUCTIONS,
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer),
            resource_server_url=AnyHttpUrl(resource_url),
            required_scopes=[],  # области не фильтруем: права — роли/предикат §3.2
            validate_token_resource=False,  # Keycloak без RFC 8707 resource-байнда
        ),
    )

    @server.tool(
        name="kb_search",
        description=(
            "Семантический поиск по материалам базы знаний. Возвращает до k "
            "фрагментов (чанков) с оценками релевантности, метаданными и "
            "названием материала. mode='vector' — чисто векторный поиск; "
            "mode='hybrid' — слияние RRF с полнотекстовым. Права пользователя "
            "применяются автоматически."
        ),
    )
    def kb_search(
        query: str,
        k: int = 10,
        mode: str = "vector",
        group_id: str | None = None,
        include_subgroups: bool = True,
    ) -> dict[str, Any]:
        """Поиск по чанкам (RAG_DESIGN §7.1-2): те же лимиты, что у REST."""
        return _kb_search_impl(query, k=k, mode=mode, group_id=group_id,
                               include_subgroups=include_subgroups)

    @server.tool(
        name="kb_groups",
        description=(
            "Дерево групп базы знаний — чтобы узнать group_id для фильтра "
            "kb_search. Возвращает до limit групп (имя, id, путь)."
        ),
    )
    def kb_groups(limit: int = 100) -> dict[str, Any]:
        """Список групп (read-only): имя/id/path — для фильтра поиска."""
        return _kb_groups_impl(limit=limit)

    return server


def mcp_asgi_app():
    """Starlette-приложение MCP (streamable HTTP) для монтирования в FastAPI.

    stateless_http: без сессий — каждый POST самодостаточен (проще клиентам и
    балансировке); json_response: ответы JSON, не SSE-потоки.
    """
    global _mcp_server
    _mcp_server = _build_server()
    assert _mcp_server is not None
    return _mcp_server.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False  # Host контролирует nginx
        ),
    )


@asynccontextmanager
async def mcp_lifespan(_app: Any) -> AsyncIterator[None]:
    """Хост-приложение владеет lifespan сессии MCP (Mount гасит собственный)."""
    if _mcp_server is None:
        yield
        return
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(_mcp_server.session_manager.run())
        yield
