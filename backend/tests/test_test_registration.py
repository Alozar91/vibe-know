# Тестовая регистрация с выбором роли (вне LLD — фича стенда, флаг KB_TEST_REGISTRATION).
# Аутентификация подменена фикстурами (conftest); introspection не вызывается.
# СА из фикстуры client уже имеет роль через is_super, но не через user_roles —
# оффер ему тоже доступен (ролей в user_roles нет), что соответствует модели.
import pytest

from app.config import get_settings
from app.use_cases.users.test_registration import feature_enabled


@pytest.fixture()
def feature_on(monkeypatch):
    monkeypatch.setenv("KB_TEST_REGISTRATION", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def feature_off(monkeypatch):
    monkeypatch.setenv("KB_TEST_REGISTRATION", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def selectable(client):
    """Роли, которые оффер предлагает на выбор (без СА/виртуальной)."""
    return [
        x
        for x in client.get("/api/v1/roles").json()
        if not x["is_virtual_all_users"] and x["name"] != "Системный администратор"
    ]


def test_feature_disabled_by_default():
    # default в Settings: test_registration = False (не для продуктива)
    get_settings.cache_clear()
    assert feature_enabled() is False
    get_settings.cache_clear()


def test_offer_disabled_when_flag_off(feature_off, client):
    r = client.get("/api/v1/me/test-registration")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["available"] is False
    assert body["roles"] == []


def test_offer_lists_seed_roles(feature_on, client):
    r = client.get("/api/v1/me/test-registration")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["available"] is True
    names = [x["name"] for x in body["roles"]]
    assert names == ["Читатель", "Автор", "Рецензент", "Публикатор"]


def test_choose_role_success(feature_on, client, db):
    import uuid

    from sqlalchemy import select

    from app.db import models

    reader = next(x for x in selectable(client) if x["name"] == "Читатель")
    me_id = client.get("/api/v1/me").json()["id"]
    r = client.post("/api/v1/me/test-registration", json={"role_id": reader["id"]})
    assert r.status_code == 200
    assert r.json() == {"user_id": me_id, "role": "Читатель"}

    link = db.execute(
        select(models.UserRole).where(models.UserRole.user_id == uuid.UUID(me_id))
    ).scalars().all()
    assert len(link) == 1
    me = client.get("/api/v1/me").json()
    assert me["roles"] == ["Читатель"]


def test_choose_role_twice_conflict(feature_on, client):
    reader = next(x for x in selectable(client) if x["name"] == "Читатель")
    assert client.post("/api/v1/me/test-registration", json={"role_id": reader["id"]}).status_code == 200
    # Повторный выбор — 409 (одноразовость; смену роли выполняет СА)
    r2 = client.post("/api/v1/me/test-registration", json={"role_id": reader["id"]})
    assert r2.status_code == 409


def test_choose_role_forbidden_roles(feature_on, client):
    roles = client.get("/api/v1/roles").json()
    sa = next(x for x in roles if x["name"] == "Системный администратор")
    virtual = next(x for x in roles if x["is_virtual_all_users"])
    for role in (sa, virtual):
        r = client.post("/api/v1/me/test-registration", json={"role_id": role["id"]})
        assert r.status_code == 400


def test_choose_role_unknown(feature_on, client):
    r = client.post(
        "/api/v1/me/test-registration",
        json={"role_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 400


def test_choose_role_bad_uuid(feature_on, client):
    r = client.post("/api/v1/me/test-registration", json={"role_id": "не-uuid"})
    assert r.status_code == 400


def test_choose_role_flag_off(feature_off, client):
    reader = next(x for x in selectable(client) if x["name"] == "Читатель")
    r = client.post("/api/v1/me/test-registration", json={"role_id": reader["id"]})
    assert r.status_code == 403


def test_offer_unavailable_after_roles_assigned(feature_on, client, db):
    """Роль назначена СА (user_roles) — оффер больше не available."""
    from tests.conftest import _make_principal

    target = _make_principal(db, "Петров Пётр")
    tid = str(target.user_id)
    reader = next(x for x in selectable(client) if x["name"] == "Читатель")
    assert client.put(f"/api/v1/users/{tid}/roles/{reader['id']}").status_code == 204

    # От имени Петрова: as_user создаёт свой principal
    c = as_client_for(db, target)
    body = c.get("/api/v1/me/test-registration").json()
    assert body["available"] is False
    r = c.post("/api/v1/me/test-registration", json={"role_id": reader["id"]})
    assert r.status_code == 409


def as_client_for(db, principal):
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: principal
    return TestClient(app)
