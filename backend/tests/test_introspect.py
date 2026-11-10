# Юнит-тесты интроспекции (LLD §10): fail-closed на active=false и сбои сервиса.
import httpx
import pytest

from app.use_cases.errors import DomainError
from app.use_cases.users.introspect_token import introspect_token


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _patch_call(monkeypatch, outcomes):
    """Подмена _call_introspection: outcomes — список ответов/исключений по порядку."""
    calls = {"n": 0}

    def fake(token):
        outcome = outcomes[min(calls["n"], len(outcomes) - 1)]
        calls["n"] += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(
        "app.use_cases.users.introspect_token._call_introspection", fake
    )
    return calls


def test_expired_token_active_false_401(monkeypatch):
    """LLD §10: истёкший токен — Keycloak отвечает 200 {"active": false} → 401 (не 500)."""
    _patch_call(monkeypatch, [{"active": False}])
    with pytest.raises(DomainError) as e:
        introspect_token("expired-token")
    assert e.value.status == 401 and e.value.code == "UNAUTHENTICATED"


def test_active_without_sub_401(monkeypatch):
    """LLD §10: active=true без sub — токен непригоден → 401 (fail-closed)."""
    _patch_call(monkeypatch, [{"active": True}])
    with pytest.raises(DomainError) as e:
        introspect_token("odd-token")
    assert e.value.status == 401 and e.value.code == "UNAUTHENTICATED"


def test_valid_token_passes(monkeypatch):
    """Валидный токен: active=true + sub — проходит, словарь возвращается как есть."""
    info = {"active": True, "sub": "kc-1", "preferred_username": "ivanov"}
    calls = _patch_call(monkeypatch, [info])
    assert introspect_token("good") is info
    assert calls["n"] == 1  # без ретрая


def test_network_error_retry_then_401(monkeypatch):
    """LLD §10: 1 повтор при сетевом сбое; оба сбойные → 401."""
    calls = _patch_call(monkeypatch, [httpx.ConnectError("down"), httpx.ConnectError("down")])
    with pytest.raises(DomainError) as e:
        introspect_token("any")
    assert e.value.status == 401
    assert calls["n"] == 2  # был ретрай


def test_network_error_first_retry_succeeds(monkeypatch):
    """Первый вызов упал, повтор прошёл — 200-ответ принимается."""
    info = {"active": True, "sub": "kc-1"}
    calls = _patch_call(monkeypatch, [httpx.ConnectError("down"), info])
    assert introspect_token("any") is info
    assert calls["n"] == 2
