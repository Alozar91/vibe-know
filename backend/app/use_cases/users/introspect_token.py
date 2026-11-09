# Use-case: Token Introspection (LLD §10, FR-011, HLD §6.1).
# fail-closed: любой сбой/active=false → DomainError 401; таймаут 2 с, 1 повтор.
import base64
from typing import Any

import httpx

from app.config import get_settings
from app.use_cases.errors import DomainError


def _fail(detail: str) -> DomainError:
    return DomainError(
        status=401, code="UNAUTHENTICATED", title="Требуется аутентификация", detail=detail,
    )


def _basic_auth_header(client_id: str, client_secret: str) -> dict[str, str]:
    raw = f"{client_id}:{client_secret}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _call_introspection(token: str) -> dict[str, Any]:
    """Один вызов introspection; httpx.HTTPError пробрасывается выше (логика ретрая)."""
    s = get_settings()
    with httpx.Client(timeout=2.0) as client:
        r = client.post(
            s.oidc_introspection_url,
            data={"token": token},
            headers=_basic_auth_header(s.oidc_client_id, s.oidc_client_secret),
        )
    if r.status_code != 200:
        raise _fail("Токен не принят сервисом аутентификации")
    return r.json()


def introspect_token(token: str) -> dict[str, Any]:
    """Интроспекция на каждый запрос без кэша (HLD §6.1, Приложение А №12).

    1 повтор при сетевом сбое (LLD §10); не-200/active=false → 401 (fail-closed).
    """
    try:
        return _call_introspection(token)
    except httpx.HTTPError:
        try:
            return _call_introspection(token)
        except httpx.HTTPError:
            raise _fail("Сервис аутентификации недоступен")
