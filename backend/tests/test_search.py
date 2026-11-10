# Тесты этапа 8: поиск (LLD §7; US-034–036, US-051).
# FTS/trgm — PG-specific; на SQLite проверяются контракт API, фильтры,
# права (предикат §3.2), аналитика и search_opens. FTS-ветка — приёмка на живом стеке.
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_current_user
from app.db import models
from app.main import app


def _mk_group(client, name, parent_id=None):
    r = client.post("/api/v1/groups", json={"name": name, "parent_id": parent_id})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_type(client, name="Тип"):
    r = client.post("/api/v1/types", json={"name": name, "attribute_ids": []})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_attr(client, name, vt, **kw):
    r = client.post("/api/v1/attributes", json={"name": name, "value_type": vt, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_material(client, name, group_id, type_id, **kw):
    r = client.post("/api/v1/materials", json={
        "name": name, "group_id": group_id, "type_id": type_id, **kw,
    })
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def env(client, db):
    """СА + материалы для поиска: published (2), draft, archived."""
    g1 = _mk_group(client, "Группа-поиск")
    g2 = _mk_group(client, "Подгруппа-поиск", parent_id=g1["id"])
    t = _mk_type(client, "Тип-поиск")

    m1 = _mk_material(client, "Инструкция по парацетамолу", g1["id"], t["id"],
                      text_content="Инструкция лекарственного средства, описание применения")
    m2 = _mk_material(client, "Регламент хранения", g2["id"], t["id"],
                      text_content="Температура хранения лекарств")
    m3 = _mk_material(client, "Черновик отчёта", g1["id"], t["id"],
                      text_content="Неопубликованный отчёт")
    m4 = _mk_material(client, "Архивная инструкция", g1["id"], t["id"],
                      text_content="Устаревшая инструкция")

    # Статусы: m1/m2 — published, m3 — draft, m4 — archived
    db.execute(
        models.__dict__["Material"].__table__.update()
        .where(models.Material.id == uuid.UUID(m1["id"]))
        .values(status="published", published_at=models.Material.__table__.c.updated_at)
    )
    db.execute(
        models.Material.__table__.update()
        .where(models.Material.id == uuid.UUID(m2["id"]))
        .values(status="published")
    )
    db.execute(
        models.Material.__table__.update()
        .where(models.Material.id == uuid.UUID(m4["id"]))
        .values(status="archived")
    )
    db.commit()
    return {
        "group": g1, "subgroup": g2, "type": t,
        "published1": m1, "published2": m2, "draft": m3, "archived": m4,
    }


def test_search_requires_auth(client, db):
    app.dependency_overrides.pop(get_current_user, None)
    r = client.get("/api/v1/search?q=тест")
    assert r.status_code == 401


def test_search_type_not_implemented(client, env):
    r = client.get("/api/v1/search?q=x&search_type=vector")
    assert r.status_code == 400
    assert r.json()["code"] == "NOT_IMPLEMENTED"


def test_search_finds_by_name_sqlite(client, env):
    """SQLite-ветка: ILIKE по имени; published находят все."""
    r = client.get("/api/v1/search?q=парацетамол")
    assert r.status_code == 200
    names = [i["name"] for i in r.json()["items"]]
    assert "Инструкция по парацетамолу" in names


def test_search_archive_hidden_by_default(client, env):
    r = client.get("/api/v1/search?q=инструкция")
    names = [i["name"] for i in r.json()["items"]]
    assert "Архивная инструкция" not in names


def test_search_include_archive(client, env):
    r = client.get("/api/v1/search?q=инструкция&include_archive=true")
    names = [i["name"] for i in r.json()["items"]]
    assert "Архивная инструкция" in names


def test_search_draft_visible_only_to_sa(client, env):
    """US-034 ш.4: предикат прав — черновик видит только автор/процессные."""
    r = client.get("/api/v1/search?q=отчёт")
    names = [i["name"] for i in r.json()["items"]]
    # client фикстуры — СА (is_super=True) → черновик виден
    assert "Черновик отчёта" in names


def test_search_visibility_for_plain_user(client, env, as_user):
    """FR-112: обычный пользователь без прав на группу не видит ничего."""
    u = as_user("Простой юзер")
    r = u.get("/api/v1/search?q=инструкция")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_search_status_filter(client, env):
    r = client.get("/api/v1/search?q=&status=published")
    items = r.json()["items"]
    assert items and all(i["status"] == "published" for i in items)


def test_search_group_filter_includes_subgroups(client, env):
    r = client.get("/api/v1/search?q=хранения&group_id=" + env["group"]["id"])
    names = [i["name"] for i in r.json()["items"]]
    assert "Регламент хранения" in names


def test_search_master_filter(client, env):
    # Регламент (published2) станет подчинённым Инструкции (published1) — этап 7
    r = client.post(f"/api/v1/materials/{env['published1']['id']}/children", json={
        "kind": "adaptation", "group_id": env["group"]["id"],
        "name": "Регламент хранения (Адаптация)",
    })
    # мастер должен быть approved/published — m1 published, ок
    assert r.status_code == 201, r.text
    child_id = r.json()["id"]

    # запрос без первой буквы: SQLite LIKE регистрозависим для кириллицы —
    # «егламент» совпадает и с «Регламент…», и с «…регламента…»
    r = client.get("/api/v1/search?q=егламент&master_filter=children")
    ids = [i["id"] for i in r.json()["items"]]
    assert child_id in ids

    r = client.get("/api/v1/search?q=егламент&master_filter=masters")
    ids = [i["id"] for i in r.json()["items"]]
    # «мастер-материалы» = без master_id: m2 («Регламент хранения») стал
    # подчинённым → не в выдаче; m1 («Инструкция…») — самостоятельный мастер → в выдаче
    assert env["published2"]["id"] in ids and child_id not in ids


def test_search_master_filter_semantics(client, env):
    """US-036 ш.4: «только мастера» включает самостоятельные без подчинённых."""
    r = client.get("/api/v1/search?q=&master_filter=masters")
    ids = [i["id"] for i in r.json()["items"]]
    assert env["published1"]["id"] in ids


def test_search_tag_filter_anyof(client, env):
    t1 = client.post("/api/v1/tags", json={"name": "тег-А"}).json()
    t2 = client.post("/api/v1/tags", json={"name": "тег-Б"}).json()
    client.patch(f"/api/v1/materials/{env['published1']['id']}",
                 headers={"If-Match": str(env["published1"]["version"])},
                 json={"tag_ids": [t1["id"]]})
    client.patch(f"/api/v1/materials/{env['published2']['id']}",
                 headers={"If-Match": str(env["published2"]["version"])},
                 json={"tag_ids": [t2["id"]]})

    r = client.get("/api/v1/search?q=&tag_ids=" + json.dumps([t1["id"], t2["id"]]))
    ids = [i["id"] for i in r.json()["items"]]
    assert env["published1"]["id"] in ids and env["published2"]["id"] in ids


def test_search_attribute_filter_eq(client, env):
    a = _mk_attr(client, "Действующее вещество", "string")
    client.post(f"/api/v1/types/{env['type']['id']}/attributes/{a['id']}")
    client.patch(f"/api/v1/materials/{env['published1']['id']}",
                 headers={"If-Match": str(env["published1"]["version"])},
                 json={"attribute_values": [
                     {"attribute_id": a["id"], "values": ["Парацетамол"]},
                 ]})
    # substring (FR-116)
    r = client.get("/api/v1/search?q=&attribute_filters=" + json.dumps([
        {"attribute_id": a["id"], "op": "substring", "value": "раце"},
    ]))
    ids = [i["id"] for i in r.json()["items"]]
    assert env["published1"]["id"] in ids

    # eq
    r = client.get("/api/v1/search?q=&attribute_filters=" + json.dumps([
        {"attribute_id": a["id"], "op": "eq", "value": "Парацетамол"},
    ]))
    ids = [i["id"] for i in r.json()["items"]]
    assert env["published1"]["id"] in ids

    # any_of — многозначный any-of (FR-116)
    client.patch(f"/api/v1/materials/{env['published2']['id']}",
                 headers={"If-Match": str(env["published2"]["version"])},
                 json={"attribute_values": [
                     {"attribute_id": a["id"], "values": ["Ибупрофен"]},
                 ]})
    r = client.get("/api/v1/search?q=&attribute_filters=" + json.dumps([
        {"attribute_id": a["id"], "op": "any_of", "values": ["Парацетамол", "Ибупрофен"]},
    ]))
    ids = [i["id"] for i in r.json()["items"]]
    assert env["published1"]["id"] in ids and env["published2"]["id"] in ids


def test_search_number_range_filter(client, env):
    a = _mk_attr(client, "Дозировка", "number")
    client.post(f"/api/v1/types/{env['type']['id']}/attributes/{a['id']}")
    client.patch(f"/api/v1/materials/{env['published1']['id']}",
                 headers={"If-Match": str(env["published1"]["version"])},
                 json={"attribute_values": [{"attribute_id": a["id"], "values": ["500"]}]})
    client.patch(f"/api/v1/materials/{env['published2']['id']}",
                 headers={"If-Match": str(env["published2"]["version"])},
                 json={"attribute_values": [{"attribute_id": a["id"], "values": ["200"]}]})
    r = client.get("/api/v1/search?q=&attribute_filters=" + json.dumps([
        {"attribute_id": a["id"], "op": "range", "value_from": "300", "value_to": "600"},
    ]))
    ids = [i["id"] for i in r.json()["items"]]
    assert env["published1"]["id"] in ids and env["published2"]["id"] not in ids


def test_search_groups_block(client, env):
    """FR-119: найденная группа — отдельным блоком."""
    r = client.get("/api/v1/search?q=поиск")
    groups = r.json()["groups"]
    names = [g["name"] for g in groups]
    assert "Группа-поиск" in names


def test_search_groups_respects_rights(client, env, as_user):
    """FR-119: только группы с правом «Просмотр»."""
    u = as_user("Юзер без прав")
    r = u.get("/api/v1/search?q=поиск")
    assert r.json()["groups"] == []


def test_search_event_logged(client, env, db):
    """FR-127: запрос попадает в search_events (lower/trim, result_count)."""
    r = client.get("/api/v1/search?q=  ПАРАЦЕТАМОЛ  ")
    assert r.status_code == 200
    ev = db.execute(select(models.SearchEvent)).scalars().all()
    assert any(e.query_normalized == "парацетамол" for e in ev)


def test_search_zero_result_in_analytics(client, env):
    r = client.get("/api/v1/search?q=абракадабра-999")
    assert r.status_code == 200 and r.json()["items"] == []
    r2 = client.get("/api/v1/analytics/search")
    assert r2.status_code == 200
    zero = [x["query"] for x in r2.json()["zero_result_queries"]]
    assert "абракадабра-999" in zero


def test_search_event_id_and_open(client, env, db):
    """POST /search-opens (§7.6): факт открытия фиксируется."""
    r = client.get("/api/v1/search?q=парацетамол")
    ev_id = r.json()["search_event_id"]
    assert ev_id is not None
    r2 = client.post("/api/v1/search-opens", json={
        "search_event_id": ev_id, "material_id": env["published1"]["id"],
    })
    assert r2.status_code == 200
    opens = db.execute(select(models.SearchOpen)).scalars().all()
    assert len(opens) == 1


def test_search_open_unknown_event_ignored(client, env):
    """§7.6: fire-and-forget — неизвестное событие не 500."""
    r = client.post("/api/v1/search-opens", json={
        "search_event_id": str(uuid.uuid4()),
        "material_id": env["published1"]["id"],
    })
    assert r.status_code == 200


def test_analytics_requires_sa(client, env, as_user):
    u = as_user("Не СА аналитики")
    r = u.get("/api/v1/analytics/search")
    assert r.status_code == 403


def test_analytics_content(client, env):
    client.get("/api/v1/search?q=парацетамол")
    r = client.get("/api/v1/analytics/search")
    body = r.json()
    assert "top_queries" in body and "ctr" in body and "text_coverage" in body
    top = {x["query"] for x in body["top_queries"]}
    assert "парацетамол" in top
    assert body["text_coverage"]["with_text"] >= 4


def test_pagination(client, env):
    r = client.get("/api/v1/search?q=&page=1&per_page=2")
    body = r.json()
    assert body["per_page"] == 2 and body["page"] == 1
    assert len(body["items"]) <= 2 and body["total"] >= 3
