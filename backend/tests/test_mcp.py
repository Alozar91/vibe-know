# Тесты MCP-сервера (пост-MVP шаг [7] ч.5, RAG_DESIGN §8-5): read-only тулы
# kb_search/kb_groups поверх /rag/retrieve. Аутентификация подменяется на
# уровне верификатора (интроспекция не вызывается — как в conftest).
# Живой протокол (streamable HTTP, stateless, JSON) — через TestClient.
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from app.db import models

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer fake"}
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "pytest", "version": "0"}}}

_type_cache: dict = {}
_user_cache: dict = {}


def _type_id(db):
    if "id" not in _type_cache:
        t = models.MaterialType(name=f"Тип MCP {__import__('uuid').uuid4().hex[:8]}")
        db.add(t)
        db.flush()
        _type_cache["id"] = t.id
        db.commit()
    return _type_cache["id"]


def _user_id(db):
    if "id" not in _user_cache:
        u = models.User(keycloak_id=f"kc-mcp-{__import__('uuid').uuid4().hex[:8]}",
                        display_name="MCP Пользователь")
        db.add(u)
        db.flush()
        _user_cache["id"] = u.id
        db.commit()
    return _user_cache["id"]


def _make_group(db, name="Группа MCP"):
    g = models.Group(name=name, normalized_name=name.lower(), path="pending")
    db.add(g)
    db.flush()
    g.path = f"{g.id}/"
    db.commit()
    return g


def _make_material(db, group, name="Материал MCP", text="Текст материала."):
    m = models.Material(
        group_id=group.id, name=name, normalized_name=name.lower(),
        type_id=_type_id(db), status=models.MaterialStatus.published,
        author_id=_user_id(db), last_editor_id=_user_id(db),
        text_content=text,
    )
    db.add(m)
    db.flush()
    from app.use_cases.materials.versions import snapshot_from_material, commit_version

    commit_version(db, m, type("U", (), {"user_id": _user_id(db)})(),
                   snapshot=snapshot_from_material(db, m))
    db.commit()
    return m


def _call(c: TestClient, payload: dict, headers: dict | None = None) -> dict:
    r = c.post("/api/v1/mcp/", json=payload, headers=headers or MCP_HEADERS)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def mcp_client(db):
    """TestClient с MCP-маунтом; principal — собственный СА (фикстуры client нет)."""
    from app.api import mcp_server
    from app.api.deps import CurrentUser
    from app.main import app

    user = models.User(keycloak_id="kc-mcp-test-sa", display_name="MCP СА")
    db.add(user)
    db.commit()
    principal = CurrentUser(user, {"sub": user.keycloak_id, "active": True}, True)

    # Тулы берут сессию через mcp_server.get_session_factory — подменяем на
    # общую тестовую БД (прокси: close() — no-op, сессию закрывает фикстура db)
    class _SessionProxy:
        def __init__(self, s):
            self._s = s

        def __getattr__(self, name):
            return getattr(self._s, name)

        def close(self):
            pass

    class _FakeFactory:
        def __call__(self):
            return _SessionProxy(db)

    import app.api.mcp_server as ms

    orig_factory = ms.get_session_factory
    ms.get_session_factory = _FakeFactory

    class FakeVerifier(TokenVerifier):
        async def verify_token(self, token: str) -> AccessToken | None:
            ms._principal_var.set(principal)
            return AccessToken(token=token, client_id="fake", scopes=[],
                               claims={"sub": user.keycloak_id})

    srv = MCPServer(
        "kb-knowledge-test",
        token_verifier=FakeVerifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl("http://localhost:8080/realms/kb/"),
            resource_server_url=AnyHttpUrl("http://localhost/api/v1/mcp"),
            required_scopes=[],
            validate_token_resource=False,
        ),
    )

    @srv.tool(name="kb_search", description="Поиск (тест).")
    def kb_search(query: str, k: int = 10, mode: str = "vector",
                  group_id: str | None = None,
                  include_subgroups: bool = True) -> dict[str, Any]:
        return mcp_server._kb_search_impl(query, k=k, mode=mode, group_id=group_id,
                                          include_subgroups=include_subgroups)

    @srv.tool(name="kb_groups", description="Группы (тест).")
    def kb_groups(limit: int = 100) -> dict[str, Any]:
        return mcp_server._kb_groups_impl(limit=limit)

    mcp_app = srv.streamable_http_app(
        streamable_http_path="/", json_response=True, stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asynccontextmanager
    async def lifespan(_):
        async with srv.session_manager.run():
            yield

    app.mount("/api/v1/mcp", mcp_app)
    app.router.lifespan_context = lifespan

    with TestClient(app) as c:
        _call(c, INIT)  # handshake
        yield c
    # Снять маунт и lifespan, вернуть фабрику сессий (приложение глобальное)
    app.router.lifespan_context = _noop_lifespan_ctx
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/api/v1/mcp"]
    ms.get_session_factory = orig_factory


@asynccontextmanager
async def _noop_lifespan_ctx(_):
    yield


class TestMcpProtocol:
    def test_unauthenticated_401(self, db, mcp_client):
        r = mcp_client.post("/api/v1/mcp/", json={"jsonrpc": "2.0", "id": 9,
                                                  "method": "tools/list"},
                            headers={"Accept": "application/json, text/event-stream"})
        assert r.status_code == 401

    def test_tools_list(self, db, mcp_client):
        out = _call(mcp_client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in out["result"]["tools"]}
        assert names == {"kb_search", "kb_groups"}


class TestMcpTools:
    def test_kb_search_returns_chunks(self, db, mcp_client, monkeypatch):
        """kb_search: чанки с material/deep_link; вектор запроса — FakeClient."""
        from tests.test_rag_indexing import FakeClient
        from tests.test_rag_retrieve import _FakeClient as _QFake

        import app.use_cases.rag.retrieve as ret

        monkeypatch.setattr(
            ret, "_query_vector",
            lambda db_, q: "[" + ",".join(repr(float(x)) for x in _QFake()._vec(q)) + "]",
        )

        g = _make_group(db)
        m = _make_material(db, g, text="Регламент обхода оборудования. " * 20)
        from app.rag.indexing import index_material

        index_material(db, m.id, client=FakeClient())

        out = _call(mcp_client, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                 "params": {"name": "kb_search",
                                            "arguments": {"query": "регламент", "k": 5}}})
        res = out["result"]
        assert res["isError"] is False
        data = res["structuredContent"]  # dict[str, Any] → сам dict (v2 SDK)
        assert data["total"] >= 1
        item = data["items"][0]
        assert item["material"]["name"] == "Материал MCP"
        assert item["deep_link"].startswith("/materials/")

    def test_kb_groups(self, db, mcp_client):
        g = _make_group(db, name="Группа для MCP-списка")
        out = _call(mcp_client, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                 "params": {"name": "kb_groups", "arguments": {}}})
        res = out["result"]
        # Крах тула → isError=True (структуры не будет); сначала диагностика
        assert res.get("isError") is not True, res.get("content")
        data = res["structuredContent"]  # dict[str, Any] → сам dict (v2 SDK)
        ids = {x["id"] for x in data["groups"]}
        assert str(g.id) in ids
