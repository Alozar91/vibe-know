# Этап 4: права (US-043/044/045), материалы (US-005/006), атрибуты/теги материала (US-031/032).
# Предикат §3.2 проверяется сквозь API (единая семантика UI/API — FR-129).
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.api.deps import get_current_user
from app.db import models
from app.main import app


def _mk_group(client, name, parent_id=None):
    r = client.post("/api/v1/groups", json={"name": name, "parent_id": parent_id})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_type(client, name="Тип", attribute_ids=None):
    r = client.post("/api/v1/types", json={"name": name, "attribute_ids": attribute_ids or []})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_attr(client, name, value_type="string", **kw):
    r = client.post("/api/v1/attributes", json={"name": name, "value_type": value_type, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_material(client, name="Материал", group_id=None, type_id=None, **kw):
    return client.post("/api/v1/materials", json={
        "name": name, "group_id": group_id, "type_id": type_id, **kw,
    })


def _grant(client, obj_type, obj_id, role_id, entries):
    """Снапшот на объект (US-044); obj_type: group|material."""
    plural = {"group": "groups", "material": "materials"}[obj_type]
    r = client.post(f"/api/v1/{plural}/{obj_id}/permissions", json={
        "role_id": role_id, "entries": entries,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _get_role(client, name):
    body = client.get("/api/v1/roles").json()
    items = body["items"] if isinstance(body, dict) else body
    return next(x for x in items if x["name"] == name)


def _user_with_role(db, name, role_id):
    """Пользователь с назначенной ролью + его CurrentUser (без интроспекции)."""
    from tests.conftest import _make_principal

    pr = _make_principal(db, name, is_super=False)
    db.add(models_UserRole(pr.user_id, role_id))
    db.commit()
    return pr


def models_UserRole(user_id, role_id):
    from app.db import models

    return models.UserRole(user_id=user_id, role_id=role_id if isinstance(role_id, uuid.UUID) else uuid.UUID(role_id))


def _client_of(pr):
    """TestClient от имени готового principal."""
    app.dependency_overrides[get_current_user] = lambda: pr
    try:
        return TestClient(app)
    finally:
        pass  # override снимет вызывающий test-finally


def _release(pr=None):
    app.dependency_overrides.pop(get_current_user, None)


def _set_status(db, material_id, status: str):
    """Прямая установка статуса (переходы — этап 5; для проверки веток §3.2)."""
    db.execute(
        update(models.Material).where(models.Material.id == material_id)
        .values(status=models.MaterialStatus(status))
    )
    db.commit()


# --- US-045: предикат прав (сквозной) ---

def test_default_deny_no_rules(client, db, as_user):
    """US-045 шаг 4: правил нет ни на одном уровне → доступ запрещён (404/403)."""
    root = _mk_group(client, "Г")
    t = _mk_type(client)
    m = _mk_material(client, "М1", group_id=root["id"], type_id=t["id"]).json()
    c = as_user("Чужой", is_super=False)
    r = c.get(f"/api/v1/materials/{m['id']}")
    assert r.status_code == 404  # невидим = не найден (FR-067)


def test_allow_via_role_membership(client, db, as_user):
    """US-045 шаг 1–3: носитель роли с allow view на группе видит published."""
    root = _mk_group(client, "Отдел")
    t = _mk_type(client)
    m = _mk_material(client, "М3", group_id=root["id"], type_id=t["id"]).json()
    reader = _get_role(client, "Читатель")
    _grant(client, "group", root["id"], reader["id"], [{"permission": "view", "state": "allow"}])

    pr = _user_with_role(db, "Читатель Иванов", reader["id"])
    _set_status(db, uuid.UUID(m["id"]), "published")  # published = view-ветка §3.2

    c = _client_of(pr)
    try:
        r = c.get(f"/api/v1/materials/{m['id']}")
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "М3"
        r2 = c.get(f"/api/v1/materials?group_id={root['id']}")
        assert any(x["id"] == m["id"] for x in r2.json()["items"])
    finally:
        _release()


def test_allow_on_parent_group_inherited(client, db, as_user):
    """US-045 шаг 1/3: allow на вышестоящей группе наследуется вложенной (FR-101)."""
    root = _mk_group(client, "Корень")
    sub = _mk_group(client, "Под", parent_id=root["id"])
    t = _mk_type(client)
    m = _mk_material(client, "М2", group_id=sub["id"], type_id=t["id"]).json()
    reader = _get_role(client, "Читатель")
    _grant(client, "group", root["id"], reader["id"], [{"permission": "view", "state": "allow"}])

    pr = _user_with_role(db, "Наследник", reader["id"])
    _set_status(db, uuid.UUID(m["id"]), "published")

    c = _client_of(pr)
    try:
        assert c.get(f"/api/v1/materials/{m['id']}").status_code == 200
    finally:
        _release()


def test_deny_beats_allow(client, db, as_user):
    """US-045 шаг 2: deny на вложенной группе побеждает allow корня (FR-102)."""
    root = _mk_group(client, "Р2")
    sub = _mk_group(client, "П2", parent_id=root["id"])
    t = _mk_type(client)
    m = _mk_material(client, "М4", group_id=sub["id"], type_id=t["id"]).json()
    reader = _get_role(client, "Читатель")
    _grant(client, "group", root["id"], reader["id"], [{"permission": "view", "state": "allow"}])
    _grant(client, "group", sub["id"], reader["id"], [{"permission": "view", "state": "deny"}])

    pr = _user_with_role(db, "Читатель Петров", reader["id"])
    _set_status(db, uuid.UUID(m["id"]), "published")

    c = _client_of(pr)
    try:
        assert c.get(f"/api/v1/materials/{m['id']}").status_code == 404
        r = c.get(f"/api/v1/materials?group_id={root['id']}")
        assert not any(x["id"] == m["id"] for x in r.json()["items"])
    finally:
        _release()


def test_all_users_virtual_role(client, db, as_user):
    """FR-009: снапшот виртуальной роли (role_id=null) действует для всех."""
    root = _mk_group(client, "Публичное")
    t = _mk_type(client)
    m = _mk_material(client, "М5", group_id=root["id"], type_id=t["id"]).json()
    _grant(client, "group", root["id"], None, [{"permission": "view", "state": "allow"}])
    _set_status(db, uuid.UUID(m["id"]), "published")

    c = as_user("Кто угодно", is_super=False)
    assert c.get(f"/api/v1/materials/{m['id']}").status_code == 200


def test_draft_visibility_branches(client, db, as_user):
    """FR-066: draft виден автору и носителям прав процесса; view — нет."""
    root = _mk_group(client, "В3")
    t = _mk_type(client)
    author = _get_role(client, "Автор")
    reviewer = _get_role(client, "Рецензент")
    reader = _get_role(client, "Читатель")
    pr_author = _user_with_role(db, "Автор В3", author["id"])
    pr_rev = _user_with_role(db, "Рец-Петров", reviewer["id"])
    pr_read = _user_with_role(db, "Чит-Сидоров", reader["id"])
    _grant(client, "group", root["id"], author["id"], [{"permission": "create", "state": "allow"}])
    _grant(client, "group", root["id"], reviewer["id"], [{"permission": "review", "state": "allow"}])
    _grant(client, "group", root["id"], reader["id"], [{"permission": "view", "state": "allow"}])

    # материал создаёт автор (create-право)
    c_a = _client_of(pr_author)
    r = c_a.post("/api/v1/materials", json={
        "name": "М6", "group_id": root["id"], "type_id": t["id"],
    })
    assert r.status_code == 201, r.text
    m = r.json()
    _release()

    # носитель review видит draft как участник процесса (FR-066)
    c_r = _client_of(pr_rev)
    try:
        assert c_r.get(f"/api/v1/materials/{m['id']}").status_code == 200
        # править не может (нет edit)
        r = c_r.patch(f"/api/v1/materials/{m['id']}", headers={"If-Match": "1"}, json={"name": "х"})
        assert r.status_code == 403
    finally:
        _release()

    # чистый Читатель draft НЕ видит (нет прав процесса)
    c_rd = _client_of(pr_read)
    try:
        assert c_rd.get(f"/api/v1/materials/{m['id']}").status_code == 404
    finally:
        _release()


def test_super_bypasses(client, db, as_user):
    """FR-104: СА действует в обход правил."""
    root = _mk_group(client, "СА-в обход")
    t = _mk_type(client)
    m = _mk_material(client, "М7", group_id=root["id"], type_id=t["id"]).json()
    assert client.get(f"/api/v1/materials/{m['id']}").status_code == 200


def test_group_create_right(client, db, as_user):
    """US-007 A4 / FR-108: создание материала — право create в группе."""
    root = _mk_group(client, "Г8")
    other_root = _mk_group(client, "Г8-закрытая")
    t = _mk_type(client)
    author = _get_role(client, "Автор")
    pr = _user_with_role(db, "Автор Смирнов", author["id"])
    _grant(client, "group", root["id"], author["id"], [{"permission": "create", "state": "allow"}])

    c = _client_of(pr)
    try:
        r = c.post("/api/v1/materials", json={
            "name": "Мой материал", "group_id": root["id"], "type_id": t["id"],
        })
        assert r.status_code == 201, r.text
        r2 = c.post("/api/v1/materials", json={
            "name": "Чужой материал", "group_id": other_root["id"], "type_id": t["id"],
        })
        assert r2.status_code == 403
    finally:
        _release()


# --- US-044: снапшоты ---

def test_snapshot_copy_from_role_and_states(client, db, as_user):
    """US-044 шаги 1–2: копия шаблона + правка состояний allow/deny/unset."""
    root = _mk_group(client, "Г9")
    author = _get_role(client, "Автор")
    snap = _grant(client, "group", root["id"], author["id"], [])
    perms = {e["permission"]: e["state"] for e in snap["entries"]}
    assert perms == {"view": "allow", "create": "allow", "edit": "allow", "delete": "allow"}

    r = client.patch(f"/api/v1/permissions/snapshots/{snap['id']}", json={
        "entries": [
            {"permission": "view", "state": "deny"},
            {"permission": "delete", "state": "unset"},
        ],
    })
    assert r.status_code == 200, r.text
    perms = {e["permission"]: e["state"] for e in r.json()["entries"]}
    assert perms["view"] == "deny" and "delete" not in perms  # unset = запись удалена (FR-102)
    r2 = client.get(f"/api/v1/groups/{root['id']}/permissions")
    assert r2.status_code == 200 and len(r2.json()) == 1


def test_snapshot_requires_super(as_user):
    """FR-105: управление правами — только СА."""
    c = as_user("Не СА", is_super=False)
    r = c.get("/api/v1/groups/00000000-0000-0000-0000-000000000000/permissions")
    assert r.status_code == 403


# --- US-005/006: списки и разделы ---

def test_list_pagination_and_sort(client, db):
    """US-005 шаг 3 (FR-117/121): сортировка по умолчанию, пагинация."""
    root = _mk_group(client, "Г10")
    t = _mk_type(client)
    for i in range(3):
        _mk_material(client, f"М10-{i}", group_id=root["id"], type_id=t["id"])
    r = client.get(f"/api/v1/materials?group_id={root['id']}&per_page=2")
    body = r.json()
    assert body["total"] == 3 and len(body["items"]) == 2 and body["page"] == 1


def test_my_materials_shows_without_group_view(client, db, as_user):
    """FR-123: «Мои материалы» не зависит от прав на группы."""
    root = _mk_group(client, "Г12")
    t = _mk_type(client)

    from tests.conftest import _make_principal

    pr = _make_principal(db, "Автор Без Прав", is_super=False)
    m = models_Material(root["id"], t["id"], pr.user_id)
    db.add(m)
    db.commit()
    # published: групповой список требует view (у автора его нет), раздел «my» — не требует
    _set_status(db, m.id, "published")

    c = _client_of(pr)
    try:
        r = c.get("/api/v1/materials?section=my")
        assert r.status_code == 200
        assert any(x["id"] == str(m.id) for x in r.json()["items"])
        r2 = c.get(f"/api/v1/materials?group_id={root['id']}")
        assert not any(x["id"] == str(m.id) for x in r2.json()["items"])
    finally:
        _release()


def models_Material(group_id, type_id, author_id):
    from app.db import models

    return models.Material(
        group_id=uuid.UUID(group_id), name="М12", normalized_name="м12",
        type_id=uuid.UUID(type_id), author_id=author_id, last_editor_id=author_id,
    )


def test_sections_empty_ok(client, db, as_user):
    """US-006 A1: пустые разделы — без ошибок."""
    c = as_user("П", is_super=False)
    for s in ("my", "review", "archive"):
        r = c.get(f"/api/v1/materials?section={s}")
        assert r.status_code == 200 and r.json()["items"] == []


# --- Материалы: CRUD, ETag, атрибуты/теги (US-031/032) ---

def test_material_create_draft_and_conflict(client, db):
    """US-007 шаг 6 + A1: draft; дубликат имени в группе (FR-027)."""
    root = _mk_group(client, "Г13")
    t = _mk_type(client)
    m = _mk_material(client, "Доклад", group_id=root["id"], type_id=t["id"])
    assert m.status_code == 201 and m.json()["status"] == "draft"
    dup = _mk_material(client, " доклад ", group_id=root["id"], type_id=t["id"])
    assert dup.status_code == 409 and dup.json()["code"] == "NAME_CONFLICT"


def test_material_etag_flow(client, db):
    """FR-093–095: 428 без If-Match, 412 — не совпал, 200 + ETag — совпал."""
    root = _mk_group(client, "Г14")
    t = _mk_type(client)
    m = _mk_material(client, "М14", group_id=root["id"], type_id=t["id"]).json()
    r = client.patch(f"/api/v1/materials/{m['id']}", json={"name": "М14-нов"})
    assert r.status_code == 428
    r = client.patch(f"/api/v1/materials/{m['id']}", headers={"If-Match": "99"}, json={"name": "х"})
    assert r.status_code == 412
    r = client.patch(f"/api/v1/materials/{m['id']}", headers={"If-Match": str(m["version"])},
                     json={"name": "М14-нов"})
    assert r.status_code == 200 and r.headers["ETag"] == '"2"'


def test_material_attributes_and_tags(client, db):
    """US-031: атрибуты (многозначность, справочник), обязательные (FR-048), теги (лимит 20)."""
    d = client.post("/api/v1/dictionaries", json={"name": "Языки2"}).json()
    v = client.post(f"/api/v1/dictionaries/{d['id']}/values", json={"value": "Русский"}).json()
    a_req = _mk_attr(client, "Обязательный", "string", is_required=True)
    a_multi = _mk_attr(client, "Действующие вещества", "string", is_multivalue=True)
    a_dict = _mk_attr(client, "Язык", "dictionary", dictionary_id=d["id"])
    t = _mk_type(client, "Тип с атрибутами", [a_req["id"], a_multi["id"], a_dict["id"]])
    root = _mk_group(client, "Г15")

    r = _mk_material(client, "М15", group_id=root["id"], type_id=t["id"],
                     attribute_values=[
                         {"attribute_id": a_multi["id"], "values": ["Парацетамол", "Ибупрофен"]},
                         {"attribute_id": a_dict["id"], "values": [v["id"]]},
                     ])
    assert r.status_code == 409 and r.json()["code"] == "ATTRIBUTE_REQUIRED_MISSING"
    assert set(r.json()["params"]["missing"]) == {"Обязательный"}

    r = _mk_material(client, "М15", group_id=root["id"], type_id=t["id"],
                     attribute_values=[
                         {"attribute_id": a_req["id"], "values": ["значение"]},
                         {"attribute_id": a_multi["id"], "values": ["Парацетамол", "Ибупрофен"]},
                         {"attribute_id": a_dict["id"], "values": [v["id"]]},
                     ])
    assert r.status_code == 201
    card = client.get(f"/api/v1/materials/{r.json()['id']}").json()
    attrs = {a["attribute_id"]: a for a in card["attributes"]}
    assert len(attrs[a_multi["id"]]["values"]) == 2
    # dictionary-значение резолвится в текст значения справочника (FR-049, US-031)
    assert attrs[a_dict["id"]]["values"] == [v["value"]]

    from app.use_cases.materials.tags_io import TAGS_MAX
    tags = [client.post("/api/v1/tags", json={"name": f"тег{i}"}).json()["id"] for i in range(TAGS_MAX + 1)]
    r = client.patch(f"/api/v1/materials/{card['id']}", headers={"If-Match": str(card["version"])},
                     json={"tag_ids": tags})
    assert r.status_code == 409 and r.json()["code"] == "TAGS_LIMIT_EXCEEDED"


def test_orphan_values_readonly(client, db):
    """US-031 A1 / US-032 шаг 2 (FR-051): осиротевшие значения остаются, readonly."""
    a1 = _mk_attr(client, "Останется", "string")
    a2 = _mk_attr(client, "Уйдёт", "string")
    t1 = _mk_type(client, "Тип А", [a1["id"], a2["id"]])
    root = _mk_group(client, "Г16")
    m = _mk_material(client, "М16", group_id=root["id"], type_id=t1["id"],
                     attribute_values=[
                         {"attribute_id": a1["id"], "values": ["раз"]},
                         {"attribute_id": a2["id"], "values": ["два"]},
                     ]).json()
    r = client.delete(f"/api/v1/types/{t1['id']}/attributes/{a2['id']}")
    assert r.status_code == 204
    card = client.get(f"/api/v1/materials/{m['id']}").json()
    attrs = {a["name"]: a for a in card["attributes"]}
    assert attrs["Уйдёт"]["readonly"] is True and attrs["Уйдёт"]["values"] == ["два"]
    assert attrs["Останется"]["readonly"] is False


def test_change_type_keeps_old_values(client, db):
    """US-032: смена типа; обязательные нового — в том же сохранении (FR-049)."""
    a_old = _mk_attr(client, "Старый", "string")
    a_new_req = _mk_attr(client, "Новообязательный", "string", is_required=True)
    t1 = _mk_type(client, "Тип Б1", [a_old["id"]])
    t2 = _mk_type(client, "Тип Б2", [a_new_req["id"]])
    root = _mk_group(client, "Г17")
    m = _mk_material(client, "М17", group_id=root["id"], type_id=t1["id"],
                     attribute_values=[{"attribute_id": a_old["id"], "values": ["старое"]}]).json()

    r = client.patch(f"/api/v1/materials/{m['id']}", headers={"If-Match": str(m["version"])},
                     json={"type_id": t2["id"]})
    assert r.status_code == 409 and r.json()["code"] == "ATTRIBUTE_REQUIRED_MISSING"

    r = client.patch(f"/api/v1/materials/{m['id']}", headers={"If-Match": str(m["version"])},
                     json={"type_id": t2["id"],
                           "attribute_values": [{"attribute_id": a_new_req["id"], "values": ["новое"]}]})
    assert r.status_code == 200, r.text
    card = client.get(f"/api/v1/materials/{m['id']}").json()
    attrs = {a["name"]: a for a in card["attributes"]}
    assert attrs["Старый"]["readonly"] is True  # FR-051
    assert attrs["Новообязательный"]["values"] == ["новое"]


def test_material_soft_delete(client, db):
    """FR-090: soft-delete из draft; 404 после."""
    root = _mk_group(client, "Г18")
    t = _mk_type(client)
    m = _mk_material(client, "М18", group_id=root["id"], type_id=t["id"]).json()
    r = client.delete(f"/api/v1/materials/{m['id']}", headers={"If-Match": str(m["version"])})
    assert r.status_code == 204
    assert client.get(f"/api/v1/materials/{m['id']}").status_code == 404
