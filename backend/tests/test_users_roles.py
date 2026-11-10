# Этап 2: учётки и роли — US-003 (заведение УЗ и назначение ролей), FR-005–013, FR-105.
# Аутентификация (introspection) подменена фикстурами; интеграционная проверка — на приёмке.


def test_me_returns_profile(client):
    r = client.get("/api/v1/me")
    assert r.status_code == 200
    body = r.json()
    assert body["display_name"] == "Тестовый СА"
    assert body["is_super"] is True
    assert body["is_service"] is False


def test_roles_seeded_five_templates(client):
    """LLD §2.6: 4 шаблона с составами + СА + виртуальная «Все пользователи» (FR-008, FR-009)."""
    r = client.get("/api/v1/roles")
    assert r.status_code == 200
    roles = {x["name"]: x for x in r.json()}
    assert roles["Читатель"]["permissions"] == ["view"]
    assert roles["Автор"]["permissions"] == ["create", "delete", "edit", "view"]
    assert roles["Рецензент"]["permissions"] == ["review", "view"]
    assert roles["Публикатор"]["permissions"] == ["archive", "publish", "view"]
    assert roles["Все пользователи"]["is_virtual_all_users"] is True


def test_role_create_duplicate_conflict(client):
    body = {"name": "Читатель", "permissions": ["view"]}
    r = client.post("/api/v1/roles", json=body)
    assert r.status_code == 409


def test_role_create_and_update(client):
    r = client.post("/api/v1/roles", json={"name": "Аналитик", "permissions": ["view", "download"]})
    assert r.status_code == 201
    rid = r.json()["id"]
    r2 = client.patch(f"/api/v1/roles/{rid}", json={"permissions": ["view"]})
    assert r2.status_code == 200
    assert r2.json()["permissions"] == ["view"]


def test_role_clone_copies_permissions(client):
    """FR-105, US-003 шаг 2: клон = копия набора прав."""
    roles = client.get("/api/v1/roles").json()
    src = next(x for x in roles if x["name"] == "Автор")
    r = client.post(f"/api/v1/roles/{src['id']}/clone")
    assert r.status_code == 201
    clone = r.json()
    assert clone["name"].startswith("Автор")
    assert clone["permissions"] == src["permissions"]


def test_assign_and_revoke_role(client, db):
    """US-003 шаг 2: СА назначает роль пользователю (FR-007)."""
    roles = client.get("/api/v1/roles").json()
    reader = next(x for x in roles if x["name"] == "Читатель")

    from tests.conftest import _make_principal

    target = _make_principal(db, "Петров Пётр")
    tid = str(target.user_id)

    r = client.put(f"/api/v1/users/{tid}/roles/{reader['id']}")
    assert r.status_code == 204

    db.expire_all()  # сбросить identity map: роли назначены запросом через ту же сессию
    card = client.get(f"/api/v1/users/{tid}").json()
    assert card["roles"] == ["Читатель"]

    # Повторное назначение идемпотентно
    assert client.put(f"/api/v1/users/{tid}/roles/{reader['id']}").status_code == 204

    r2 = client.delete(f"/api/v1/users/{tid}/roles/{reader['id']}")
    assert r2.status_code == 204
    db.expire_all()
    card = client.get(f"/api/v1/users/{tid}").json()
    assert card["roles"] == []


def test_users_list_requires_super(as_user, db):
    """FR-005/FR-104: списки пользователей — только СА; обычный пользователь — 403."""
    c = as_user("Просто пользователь", is_super=False)
    r = c.get("/api/v1/users")
    assert r.status_code == 403


def test_deactivate_user(client, db):
    """DELETE /users/{id} — деактивация (soft, FR-006/FR-011); сам себя нельзя."""
    from tests.conftest import _make_principal

    target = _make_principal(db, "Сидорова Анна")
    tid = str(target.user_id)

    r = client.delete(f"/api/v1/users/{tid}")
    assert r.status_code == 200
    assert r.json()["is_deactivated"] is True

    card = client.get(f"/api/v1/users/{tid}").json()
    assert card["is_deactivated"] is True

    # Самодеактивация запрещена
    me = client.get("/api/v1/me").json()
    r2 = client.delete(f"/api/v1/users/{me['id']}")
    assert r2.status_code == 409


def test_users_list_pagination(client, db):
    """FR-131: page/per_page, макс 200, конверт {items,total,page,per_page}."""
    from tests.conftest import _make_principal

    for i in range(3):
        _make_principal(db, f"Юзер {i}")

    r = client.get("/api/v1/users?page=1&per_page=2")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items", "total", "page", "per_page"}
    assert body["per_page"] == 2
    assert body["total"] >= 4  # СА + 3 юзера

    r2 = client.get("/api/v1/users?per_page=500")
    assert r2.json()["per_page"] == 200  # жёсткий максимум
