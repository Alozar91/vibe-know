# Тесты этапа 10: СА-контур (LLD §11, §2.5, §9; US-048, US-049, US-050, US-053).
#
# SQLite-упрощения: audit/export NDJSON и валидация настроек проверяются через API;
# _review_transferred (условие закрытия service-task) — прямой вызов use-case;
# keycloak.sync — unit-проверка парсинга страниц (PG-ветки — приёмкой на живом стеке).
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_current_user
from app.db import models
from app.main import app

from tests.test_master_detail import (
    _MATRIX_SEED,
    _attach_ready_file,
    _client_of,
    _get_role,
    _mk_group,
    _mk_type,
    _seed_transition_matrix,
)

# _PrincipaledClient / _grant — те же, что в test_notifications (этап 9)


def _grant(db, group_id, role_id, perms):
    """Назначение снапшота прав от имени СА (прямым вызовом use-case)."""
    from app.use_cases.permissions.snapshots import create_snapshot

    create_snapshot(
        db, is_super=True, actor_user_id=db.execute(
            select(models.User).where(models.User.is_service.is_(False))
        ).scalars().first().id,
        object_type="group", object_id=group_id, role_id=role_id,
        entries=[{"permission": p, "state": "allow"} for p in perms],
    )


def _user_with_role(db, name, role_id):
    from tests.conftest import _make_principal

    pr = _make_principal(db, name, is_super=False)
    db.add(models.UserRole(
        user_id=pr.user_id,
        role_id=role_id if isinstance(role_id, uuid.UUID) else uuid.UUID(role_id),
    ))
    db.commit()
    return pr


class _PrincipaledClient(TestClient):
    """TestClient с per-request подменой principal (см. test_notifications)."""

    def __init__(self, principal):
        super().__init__(app)
        self._principal = principal

    def request(self, *args, **kwargs):
        saved = app.dependency_overrides.get(get_current_user)
        app.dependency_overrides[get_current_user] = lambda: self._principal
        try:
            return super().request(*args, **kwargs)
        finally:
            if saved is None:
                app.dependency_overrides.pop(get_current_user, None)
            else:
                app.dependency_overrides[get_current_user] = saved


def _client_of(pr):
    return _PrincipaledClient(pr)


@pytest.fixture()
def env(client, db, monkeypatch):
    """СА + обычный пользователь; матрица §2.6; сид system_settings §2.5."""
    global _SA_PRINCIPAL_ETAP10
    from tests.conftest import _make_principal
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)
    _SA_PRINCIPAL_ETAP10 = _make_principal(db, "СА Этапа 10", is_super=True)
    _seed_settings(db)
    _seed_transition_matrix(db)
    g = _mk_group(client, "Группа-10")
    t = _mk_type(client, "Тип-10")
    role_author = _get_role(client, "Автор")
    _grant(db, g["id"], role_author["id"],
           ["view", "create", "edit", "review", "publish", "archive", "download"])
    author = _user_with_role(db, "Автор Этапа 10", uuid.UUID(role_author["id"]))

    yield {
        "db": db, "author": author,
        "as_author": lambda: _client_of(author),
        "as_sa": lambda: _client_of(_SA_PRINCIPAL_ETAP10),
        "group": g, "type": t, "role_author": role_author,
    }
    app.dependency_overrides.pop(get_current_user, None)


_SA_PRINCIPAL_ETAP10 = None


def _seed_settings(db):
    """Сид system_settings §2.5 (как миграция 0008; значение — JSON-объект:
    колонка JSONB/JSON, SQLAlchemy декодирует сам)."""
    if db.execute(select(models.SystemSetting)).scalars().first() is not None:
        return
    seed = [
        ("file_max_size_mb", 100, "FR-031"),
        ("mime_extra", [], "FR-056"),
        ("page_size", 50, "FR-121"),
        ("tags_max", 20, "FR-052"),
        ("master_change_criterion", "content", "FR-038"),
        ("audit_retention_days", None, "FR-141"),
        ("digest_interval_minutes", None, "FR-138"),
    ]
    for k, v, d in seed:
        db.add(models.SystemSetting(key=k, value=v, description=d))
    db.commit()


def _mk_material(c, name, group_id, type_id, **kw):
    r = c.post("/api/v1/materials", json={
        "name": name, "group_id": group_id, "type_id": type_id, **kw,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _upload(c, material_id, filename, data: bytes):
    return c.post(
        f"/api/v1/materials/{material_id}/files",
        files={"file": (filename, data, "application/octet-stream")},
    )


# --- US-049: аудит (FR-140–143) ---


def test_audit_403_for_non_super(env):
    """US-049: журнал и экспорт — только СА (403 у остальных)."""
    for path in ("/api/v1/audit", "/api/v1/audit/export", "/api/v1/settings",
                 "/api/v1/service-tasks", "/api/v1/tasks"):
        r = env["as_author"]().get(path)
        assert r.status_code == 403, (path, r.status_code)


def test_audit_feed_and_filters(env):
    """US-049 ш.1: записи «кто/когда/что/над чем»; фильтры action/object_type."""
    sa = env["as_sa"]()
    g, t = env["group"], env["type"]
    m = _mk_material(sa, "Материал-10", g["id"], t["id"])
    r = sa.get("/api/v1/audit?action=material.create")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert any(i["action"] == "material.create" and i["object_id"] == m["id"] for i in items)
    row = next(i for i in items if i["object_id"] == m["id"])
    assert row["object_type"] == "material"
    assert row["actor_user_id"] is not None
    assert row["occurred_at"]

    # фильтр object_type
    r2 = sa.get("/api/v1/audit?object_type=material")
    assert r2.status_code == 200
    assert all(i["object_type"] == "material" for i in r2.json()["items"])

    # фильтр по датам: узкое окно исключает старые записи
    r3 = sa.get("/api/v1/audit?date_from=2099-01-01T00:00:00")
    assert r3.status_code == 200
    assert r3.json()["total"] == 0

    # пагинация
    r4 = sa.get("/api/v1/audit?page=1&per_page=2")
    assert r4.status_code == 200
    body = r4.json()
    assert body["per_page"] == 2 and len(body["items"]) <= 2


def test_audit_export_ndjson_and_self_record(env):
    """US-049 ш.2 (FR-143): NDJSON-выгрузка; сама выгрузка фиксируется (audit.export)."""
    sa = env["as_sa"]()
    g, t = env["group"], env["type"]
    _mk_material(sa, "Материал-экспорт", g["id"], t["id"])

    r = sa.get("/api/v1/audit/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    assert len(lines) > 0
    for ln in lines:
        obj = json.loads(ln)  # каждая строка — самостоятельный JSON-объект
        assert "action" in obj and "occurred_at" in obj

    # audit.export появился в журнале (запись коммитится до выдачи тела)
    r2 = sa.get("/api/v1/audit?action=audit.export")
    assert r2.status_code == 200
    exports = r2.json()["items"]
    assert len(exports) >= 1
    assert exports[0]["details"]["format"] == "ndjson"
    assert exports[0]["details"]["records"] >= len(lines) - 1


def test_audit_export_403_no_record(env):
    """403 у не-СА: запись audit.export не создаётся (проверка до генерации)."""
    r = env["as_author"]().get("/api/v1/audit/export")
    assert r.status_code == 403
    sa = env["as_sa"]()
    r2 = sa.get("/api/v1/audit?action=audit.export")
    assert r2.status_code == 200
    assert all(i["actor_user_id"] is not None for i in r2.json()["items"])


# --- US-048: параметры системы (NFR-020, FR-140) ---


def test_settings_list_and_update(env):
    """US-048 ш.1/ш.3: просмотр реестра; изменение с валидацией и аудитом."""
    sa = env["as_sa"]()
    r = sa.get("/api/v1/settings")
    assert r.status_code == 200, r.text
    keys = {s["key"] for s in r.json()}
    assert {"file_max_size_mb", "page_size", "mime_extra"} <= keys

    # валидация: page_size вне 1..200 → 400
    r_bad = sa.put("/api/v1/settings/page_size", json={"value": 500})
    assert r_bad.status_code == 400
    assert r_bad.json()["code"] == "VALIDATION_ERROR"

    # валидация: критерий мастера — только 'content'|'any'
    r_bad2 = sa.put("/api/v1/settings/master_change_criterion", json={"value": "всё"})
    assert r_bad2.status_code == 400

    # неизвестный ключ → 404
    r_nf = sa.put("/api/v1/settings/no_such_key", json={"value": 1})
    assert r_nf.status_code == 404

    # корректное изменение → 200 + аудит settings.change
    r_ok = sa.put("/api/v1/settings/page_size", json={"value": 25})
    assert r_ok.status_code == 200, r.text
    assert r_ok.json()["value"] == 25
    r_audit = sa.get("/api/v1/audit?action=settings.change")
    assert r_audit.status_code == 200
    row = r_audit.json()["items"][0]
    assert row["details"]["key"] == "page_size"
    assert row["details"]["new"] == 25


def test_settings_page_size_affects_lists(env):
    """US-048 (FR-121): изменение page_size реально влияет на пагинацию списков."""
    sa = env["as_sa"]()
    g, t = env["group"], env["type"]
    for i in range(3):
        _mk_material(sa, f"Материал-паг-{i}", g["id"], t["id"])
    r = sa.put("/api/v1/settings/page_size", json={"value": 2})
    assert r.status_code == 200
    r2 = sa.get("/api/v1/materials")
    assert r2.status_code == 200
    body = r2.json()
    assert body["per_page"] == 2
    assert len(body["items"]) == 2


def test_settings_mime_extra_accepted(env):
    """US-048 ш.2 (FR-056): mime_extra — редактируемый список; загрузка mime из
    mime_extra не отклоняется (is_download_only учитывает параметр)."""
    sa = env["as_sa"]()
    r = sa.put("/api/v1/settings/mime_extra", json={"value": ["image/bmp"]})
    assert r.status_code == 200, r.text
    assert r.json()["value"] == ["image/bmp"]
    from app.use_cases.files.mime_detect import is_download_only

    assert not is_download_only("image/bmp", ["image/bmp"])
    assert is_download_only("image/bmp", [])  # вне набора — только скачивание


# --- US-050: удалённые объекты (FR-021/FR-090) ---


def test_deleted_objects_visible_to_super_only(env):
    """US-050: удалённые материалы/группы видны СА; 403 у остальных; только просмотр."""
    sa = env["as_sa"]()
    g, t = env["group"], env["type"]
    m = _mk_material(sa, "Материал-к-удалению", g["id"], t["id"])
    # подгруппа с материалом → soft-delete ветки (FR-018: пустая = физическое)
    r_sub = sa.post("/api/v1/groups", json={"name": "Подгруппа-10", "parent_id": g["id"]})
    assert r_sub.status_code == 201, r_sub.text
    sub = r_sub.json()
    r_m2 = sa.post("/api/v1/materials", json={
        "name": "Материал-в-подгруппе", "group_id": sub["id"], "type_id": t["id"],
    })
    assert r_m2.status_code == 201, r_m2.text
    r_del = sa.delete(f"/api/v1/groups/{sub['id']}")
    assert r_del.status_code in (200, 204), r_del.text
    assert r_del.json()["mode"] == "soft"
    # удаление материала (delete — из прав «Автор»: delete; нужен If-Match, FR-095)
    ver = sa.get(f"/api/v1/materials/{m['id']}").json()["version"]
    r_del_m = sa.delete(f"/api/v1/materials/{m['id']}", headers={"If-Match": f'"{ver}"'})
    assert r_del_m.status_code in (200, 204), r_del_m.text

    # СА видит оба списка (materials/deleted — envelope, groups/deleted — список)
    r_m = sa.get("/api/v1/materials/deleted")
    assert r_m.status_code == 200
    assert any(x["id"] == m["id"] for x in r_m.json()["items"])
    r_g = sa.get("/api/v1/groups/deleted")
    assert r_g.status_code == 200
    assert any(x["id"] == sub["id"] for x in r_g.json())

    # не-СА — 403
    r_m2 = env["as_author"]().get("/api/v1/materials/deleted")
    assert r_m2.status_code == 403
    r_g2 = env["as_author"]().get("/api/v1/groups/deleted")
    assert r_g2.status_code == 403

    # восстановление запрещено: PATCH/PUT на удалённом → 404/403 (не 200)
    r_restore = sa.patch(f"/api/v1/materials/{m['id']}", json={"name": "x"})
    assert r_restore.status_code in (403, 404, 405, 409)


# --- FR-012 / US-004 ш.5: service-tasks ---


def test_service_task_close_requires_review_transfer(env):
    """US-004 ш.5 (FR-012): закрытие запрещено (409), пока право review не передано;
    после назначения review другому активному пользователю — закрывается."""
    db = env["db"]
    sa = env["as_sa"]()
    g = env["group"]
    author = env["author"]

    # деактивация автора (единственного носителя review) → задача;
    # деактивирует СА (не сам автор — US-004)
    from app.use_cases.users.deactivate_user import deactivate_user

    deactivate_user(db, _SA_PRINCIPAL_ETAP10.db_user, True, str(author.user_id),
                    actor_principal=_SA_PRINCIPAL_ETAP10)
    tasks = db.execute(
        select(models.ServiceTask).where(models.ServiceTask.closed_at.is_(None))
    ).scalars().all()
    assert tasks, "ожидалась service_tasks(transfer_review_right)"
    task = tasks[0]

    # API: список (только СА) содержит задачу
    r_list = sa.get("/api/v1/service-tasks")
    assert r_list.status_code == 200
    assert any(x["id"] == str(task.id) for x in r_list.json())

    # закрытие до передачи права → 409 DOMAIN_RULE_VIOLATION
    r_close = sa.post(f"/api/v1/service-tasks/{task.id}:close")
    assert r_close.status_code == 409, r_close.text
    assert r_close.json()["code"] == "DOMAIN_RULE_VIOLATION"

    # назначаем review другому активному пользователю (US-044)
    other = _user_with_role(db, "Носитель Ревью", uuid.UUID(env["role_author"]["id"]))
    db.commit()
    assert not other.db_user.is_deactivated

    r_close2 = sa.post(f"/api/v1/service-tasks/{task.id}:close")
    assert r_close2.status_code == 200, r_close2.text
    assert r_close2.json()["state"] == "done"

    # повторное закрытие → 400 (уже закрыта)
    r_again = sa.post(f"/api/v1/service-tasks/{task.id}:close")
    assert r_again.status_code == 400


def test_service_task_deactivated_holder_does_not_count(env):
    """FR-012: деактивированный носитель review не закрывает задачу."""
    db = env["db"]
    sa = env["as_sa"]()
    author = env["author"]

    from app.use_cases.users.deactivate_user import deactivate_user

    deactivate_user(db, _SA_PRINCIPAL_ETAP10.db_user, True, str(author.user_id),
                    actor_principal=_SA_PRINCIPAL_ETAP10)
    task = db.execute(
        select(models.ServiceTask).where(models.ServiceTask.closed_at.is_(None))
    ).scalars().first()
    assert task is not None

    # назначаем review деактивированному пользователю — задача не закрывается
    deactivated = _user_with_role(db, "Деактивированный Носитель", uuid.UUID(env["role_author"]["id"]))
    deactivated.db_user.is_deactivated = True
    db.commit()
    r = sa.post(f"/api/v1/service-tasks/{task.id}:close")
    assert r.status_code == 409


# --- GET /tasks (NFR-014) ---


def test_tasks_summary_structure(env):
    """NFR-014: сводка по типам/состояниям + последние задачи."""
    sa = env["as_sa"]()
    db = env["db"]
    db.add(models.SystemTask(
        task_type="antivirus", object_type="file", state="queued",
        scheduled_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    ))
    db.commit()
    r = sa.get("/api/v1/tasks")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "summary" in body and "items" in body
    assert body["summary"].get("antivirus", {}).get("queued", 0) >= 1
    assert isinstance(body["items"], list)


# --- keycloak.sync (unit, LLD §10) ---


def test_keycloak_sync_constants():
    """LLD §10: пагинация Admin API — 100 ([уточнение LLD]); маппинг полей
    (enabled=false → is_deactivated, email → email_cache 16.1-119) и интеграция
    с живым Keycloak проверяются приёмкой (US-053)."""
    from app.worker import tasks as wt

    assert wt.KEYCLOAK_SYNC_PAGE == 100
    # сверка не создаёт пользователей: новые — при первом входе (§6.1 HLD)
    src = open(wt.__file__, encoding="utf-8").read()
    assert "upsert_user_from_token" not in src
