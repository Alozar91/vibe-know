# Тесты этапа 9: уведомления (LLD §8, §9; US-004, US-039, US-040, US-047).
#
# SQLite-упрощения: диспетчер/анти-шум тестируются прямым вызовом dispatch_events
# (worker-задачи на SQLite возвращают skipped — PG-ветки проверяются приёмкой);
# события в транзакциях — через API-мутации с последующим прогоном диспетчера.
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
    """TestClient, устанавливающий своего principal на каждый запрос
    (глобальный dependency_overrides — один слот; несколько клиентов
    в одном тесте требуют per-request подмены)."""

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


def _transition(c, material_id, to_status, version=None, confirm_cascade=False):
    if version is None:
        version = c.get(f"/api/v1/materials/{material_id}").json()["version"]
    r = c.post(f"/api/v1/materials/{material_id}/transitions",
               json={"to_status": to_status, "confirm_cascade": confirm_cascade},
               headers={"If-Match": f'"{version}"'})
    assert r.status_code == 200, r.text
    return r.json()


def _dispatch(db):
    """Прогон диспетчера (§8.2)."""
    from app.use_cases.notifications.dispatch import dispatch_events

    return dispatch_events(db)


def _events(db):
    return list(db.execute(
        select(models.NotificationEvent).order_by(models.NotificationEvent.created_at)
    ).scalars().all())


def _notifs(db, uid=None, event_type=None):
    stmt = select(models.Notification)
    if uid is not None:
        stmt = stmt.where(models.Notification.recipient_id == uid)
    if event_type:
        stmt = stmt.where(models.Notification.event_type == event_type)
    return list(db.execute(stmt).scalars().all())


@pytest.fixture()
def env(client, db, monkeypatch):
    """СА + автор с правами edit/review в группе; матрица §2.6."""
    global _SA_PRINCIPAL_ETAP9
    from tests.conftest import _make_principal
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)
    _SA_PRINCIPAL_ETAP9 = _make_principal(db, "СА Этапа 9", is_super=True)
    # FR-104: СА — носитель шаблона «Системный администратор» (для file_blocked)
    sa_role = db.execute(
        select(models.Role).where(models.Role.name == "Системный администратор")
    ).scalar_one()
    db.add(models.UserRole(user_id=_SA_PRINCIPAL_ETAP9.user_id, role_id=sa_role.id))
    db.commit()
    _seed_transition_matrix(db)
    g = _mk_group(client, "Группа-9")
    t = _mk_type(client, "Тип-9")
    role_author = _get_role(client, "Автор")
    _grant(db, g["id"], role_author["id"],
           ["view", "create", "edit", "review", "publish", "archive", "download"])
    author = _user_with_role(db, "Автор Этапа 9", uuid.UUID(role_author["id"]))

    # Сид триггеров §2.6 (в тестовой БД из моделей — без миграций)
    _seed_triggers(db)

    yield {
        "db": db, "author": author,
        "as_author": lambda: _client_of(author),
        "as_sa": lambda: _client_of(_SA_PRINCIPAL_ETAP9),
        "group": g, "type": t, "role_author": role_author,
    }
    app.dependency_overrides.pop(get_current_user, None)


_SA_PRINCIPAL_ETAP9 = None


def _seed_triggers(db):
    """Сид триггеров §2.6 (как миграция 0009)."""
    if db.execute(select(models.NotificationTrigger)).scalars().first() is not None:
        return
    seed = [
        ("material_sent_to_review", True, [{"type": "permission_holder", "permission": "review"}]),
        ("material_rejected", True, [{"type": "fact_author"}]),
        ("material_changed_on_review", True, [
            {"type": "fact_author"},
            {"type": "permission_holder", "permission": "review"},
        ]),
        ("master_changed", True, [
            {"type": "fact_author", "scope": "children"},
            {"type": "fact_signatory", "scope": "children"},
        ]),
        ("child_auto_archived", True, [{"type": "fact_author"}, {"type": "fact_signatory"}]),
        ("material_archived", True, [{"type": "fact_author"}, {"type": "fact_signatory"}]),
        ("status_changed", False, [{"type": "fact_author"}]),
    ]
    for et, en, rc in seed:
        db.add(models.NotificationTrigger(
            event_type=et, enabled=en, recipients=json.dumps(rc, ensure_ascii=False)
        ))
    db.commit()


def _mk_material(c, name, group_id, type_id, **kw):
    r = c.post("/api/v1/materials", json={
        "name": name, "group_id": group_id, "type_id": type_id, **kw,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _mk_master_with_child(c, db, env, master_name, child_name, with_text=True):
    """Мастер (approved, файл) + подчинённый-адаптация (для master_changed)."""
    master = _mk_material(c, master_name, env["group"]["id"], env["type"]["id"],
                          text_content="Текст мастера" if with_text else None)
    _attach_ready_file(client=c, db=db, material_id=master["id"])
    _transition(c, master["id"], "in_review")
    approved = _transition(c, master["id"], "approved")
    child = c.post(f"/api/v1/materials/{master['id']}/children", json={
        "kind": "adaptation", "group_id": env["group"]["id"], "name": child_name,
    })
    assert child.status_code == 201, child.text
    return master, child.json(), approved["version"]


# --- События в транзакциях (§8.1) ---

def test_event_on_sent_to_review(env):
    """→ in_review публикует material_sent_to_review в транзакции."""
    c = env["as_author"](); db = env["db"]
    m = _mk_material(c, "Материал-9а", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")
    evs = [e for e in _events(db) if str(e.material_id) == m["id"]]
    assert [e.event_type for e in evs] == ["material_sent_to_review"]


def test_event_on_reject(env):
    """in_review → draft публикует material_rejected (16.1-113)."""
    c = env["as_author"](); db = env["db"]
    m = _mk_material(c, "Материал-9б", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")
    _transition(c, m["id"], "draft")
    evs = [e.event_type for e in _events(db) if str(e.material_id) == m["id"]]
    assert evs == ["material_sent_to_review", "material_rejected"]


def test_no_event_approved_to_draft(env):
    """16.1-113: отзыв утверждения approved→draft события НЕ создаёт."""
    c = env["as_author"](); db = env["db"]
    m = _mk_material(c, "Материал-9в", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")
    _transition(c, m["id"], "approved")
    _transition(c, m["id"], "draft")
    evs = [e.event_type for e in _events(db) if str(e.material_id) == m["id"]]
    assert "material_rejected" not in evs


def test_event_on_archive_and_cascade(env):
    """→ archived: мастер material_archived + child_auto_archived на каждого
    подчинённого (16.1-116); при одиночной — только material_archived."""
    c = env["as_author"](); db = env["db"]
    master = _mk_material(c, "Мастер-9", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=master["id"])
    _transition(c, master["id"], "in_review")
    approved = _transition(c, master["id"], "approved")
    child = c.post(f"/api/v1/materials/{master['id']}/children", json={
        "kind": "adaptation", "group_id": env["group"]["id"], "name": "Подчинённый-9",
    })
    assert child.status_code == 201, child.text
    child = child.json()
    _transition(c, master["id"], "published", version=approved["version"])
    _transition(c, master["id"], "archived", confirm_cascade=True)
    evs = [e.event_type for e in _events(db)]
    assert evs.count("material_archived") == 1
    assert evs.count("child_auto_archived") == 1


def test_event_on_changed_on_review(env):
    """Правка текста в in_review — material_changed_on_review (FR-085, 7.7)."""
    c = env["as_author"](); db = env["db"]
    m = _mk_material(c, "Материал-9г", env["group"]["id"], env["type"]["id"],
                     text_content="Первоначальный текст")
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")
    version = c.get(f"/api/v1/materials/{m['id']}").json()["version"]
    r = c.patch(f"/api/v1/materials/{m['id']}", json={"text_content": "Изменённый текст"},
              headers={"If-Match": f'"{version}"'})
    assert r.status_code == 200, r.text
    evs = [e.event_type for e in _events(db) if str(e.material_id) == m["id"]]
    assert evs[-1] == "material_changed_on_review"


def test_master_changed_on_content_edit(env):
    """Правка текста мастера по критерию 'content' — master_changed (16.1-111)."""
    c = env["as_author"](); db = env["db"]
    master, child, version = _mk_master_with_child(c, db, env, "Мастер-9б", "Подчинённый-9б")
    r = c.patch(f"/api/v1/materials/{master['id']}", json={"text_content": "Новый текст"},
                headers={"If-Match": f'"{version}"'})
    assert r.status_code == 200, r.text
    evs = [e.event_type for e in _events(db) if str(e.material_id) == master["id"]]
    assert "master_changed" in evs


def test_meta_only_edit_no_master_changed(env):
    """Правка только имени при критерии 'content' — события нет (FR-038)."""
    c = env["as_author"](); db = env["db"]
    master, child, version = _mk_master_with_child(
        c, db, env, "Мастер-9в", "Подчинённый-9в", with_text=False)
    r = c.patch(f"/api/v1/materials/{master['id']}", json={"name": "Мастер-9в-новый"},
                headers={"If-Match": f'"{version}"'})
    assert r.status_code == 200, r.text
    evs = [e.event_type for e in _events(db) if str(e.material_id) == master["id"]]
    assert "master_changed" not in evs


# --- Диспетчер (§8.2): получатели, исключения, анти-шум ---

def test_dispatch_recipients_review_holders(env):
    """material_sent_to_review → носители review; инициатор исключён (FR-138)."""
    c = env["as_author"](); db = env["db"]
    m = _mk_material(c, "Материал-9д", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")  # инициатор — автор
    stats = _dispatch(db)
    assert stats["events"] >= 1
    ns = _notifs(db, event_type="material_sent_to_review")
    for n in ns:
        u = db.execute(select(models.User).where(models.User.id == n.recipient_id)).scalar_one()
        print("DBG notif to:", u.display_name, "is_author:", n.recipient_id == env["author"].user_id)
    assert all(str(n.recipient_id) != str(env["author"].user_id) for n in ns)


def test_dispatch_excludes_initiator_and_deactivated(env):
    """FR-138/139/013: инициатор, деактивированные, сервисные — не получают."""
    c = env["as_author"](); db = env["db"]
    role_id = uuid.UUID(env["role_author"]["id"])
    reviewer = _user_with_role(db, "Рецензент-9", role_id)
    svc = _user_with_role(db, "Сервисная-9", role_id)
    svc.db_user.is_service = True
    deact = _user_with_role(db, "Деактивированная-9", role_id)
    deact.db_user.is_deactivated = True
    db.commit()

    m = _mk_material(c, "Материал-9е", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")  # инициатор — автор
    _dispatch(db)

    ns = _notifs(db, event_type="material_sent_to_review")
    uids = {str(n.recipient_id) for n in ns}
    assert str(reviewer.user_id) in uids           # получил
    assert str(env["author"].user_id) not in uids  # инициатор исключён (FR-138)
    assert str(svc.user_id) not in uids            # сервисная УЗ (FR-013)
    assert str(deact.user_id) not in uids          # деактивированная (FR-139)
    # только reviewer
    assert len(uids) == 1


def test_dispatch_rejected_notifies_author(env):
    """material_rejected → автор (получает, т.к. инициатор — рецензент)."""
    c = env["as_author"](); db = env["db"]
    role_id = uuid.UUID(env["role_author"]["id"])
    reviewer = _user_with_role(db, "Рецензент-9б", role_id)
    m = _mk_material(c, "Материал-9ж", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")
    _dispatch(db)
    rc = _client_of(reviewer)
    _transition(rc, m["id"], "draft")  # отклонение рецензентом
    _dispatch(db)
    ns = _notifs(db, event_type="material_rejected")
    uids = {str(n.recipient_id) for n in ns}
    assert str(env["author"].user_id) in uids
    assert str(reviewer.user_id) not in uids


def test_anti_noise_window(env):
    """Повторное событие в окне 10 мин не создаёт новое уведомление (§8.2)."""
    c = env["as_author"](); db = env["db"]
    role_id = uuid.UUID(env["role_author"]["id"])
    reviewer = _user_with_role(db, "Рецензент-9в", role_id)
    m = _mk_material(c, "Материал-9з", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")
    _dispatch(db)
    first = len(_notifs(db, event_type="material_sent_to_review"))

    # Возврат в draft и снова на ревью — в пределах окна анти-шума
    _transition(c, m["id"], "draft")
    _dispatch(db)
    _transition(c, m["id"], "in_review")
    _transition(c, m["id"], "draft")
    _transition(c, m["id"], "in_review")
    _dispatch(db)
    second = len(_notifs(db, event_type="material_sent_to_review"))
    assert second == first  # дубликаты отфильтрованы dedup_key


def test_disabled_trigger_no_notifications(env):
    """Триггер отключён → событие processed без уведомлений (US-047)."""
    c = env["as_author"](); db = env["db"]
    t = db.execute(
        select(models.NotificationTrigger)
        .where(models.NotificationTrigger.event_type == "material_sent_to_review")
    ).scalar_one()
    t.enabled = False
    db.commit()
    m = _mk_material(c, "Материал-9и", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")
    stats = _dispatch(db)
    assert stats["inapp_created"] == 0
    assert all(e.processed for e in _events(db))


def test_status_changed_general_trigger(env):
    """Общий status_changed: переход in_review→approved (не покрыт спецтриггером)
    доставляется, если триггер включён; спецсобытия не дублируются (FR-134)."""
    c = env["as_author"](); db = env["db"]
    # Получатель общего триггера — fact_last_editor... инициатор всегда
    # совпадает с автором при self-transitions; берём permission_holder(review)
    # и внешнего рецензента, чтобы уведомление кому-то пришло
    t = db.execute(
        select(models.NotificationTrigger)
        .where(models.NotificationTrigger.event_type == "status_changed")
    ).scalar_one()
    t.enabled = True
    t.recipients = json.dumps([{"type": "permission_holder", "permission": "review"}])
    role_id = uuid.UUID(env["role_author"]["id"])
    reviewer = _user_with_role(db, "Рецензент-9к", role_id)
    db.commit()

    m = _mk_material(c, "Материал-9к", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")
    _dispatch(db)
    approved = _transition(c, m["id"], "approved")
    _dispatch(db)
    evs = [e.event_type for e in _events(db) if str(e.material_id) == m["id"]]
    # draft→in_review — специализированное; in_review→approved — общий
    assert "material_sent_to_review" in evs
    assert "status_changed" in evs

    # FR-134: по одному уведомлению на переход; спецсобытие не дублируется
    ns = _notifs(db, event_type="status_changed")
    assert len(ns) == 1  # только от in_review→approved
    assert {str(n.recipient_id) for n in ns} == {str(reviewer.user_id)}

    _transition(c, m["id"], "published", version=approved["version"])
    _dispatch(db)
    # §8.2 анти-шум: повторный status_changed по тому же материалу в окне 10 мин
    # для того же получателя НЕ создаёт новое уведомление (группировка)
    ns = _notifs(db, event_type="status_changed")
    assert len(ns) == 1


def test_smtp_not_configured_no_email_state(env):
    """US-040 A1: SMTP ненастроен → email_state не ставится (in-app работает)."""
    c = env["as_author"](); db = env["db"]
    role_id = uuid.UUID(env["role_author"]["id"])
    _user_with_role(db, "Рецензент-9г", role_id)
    m = _mk_material(c, "Материал-9л", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")
    _dispatch(db)
    ns = _notifs(db, event_type="material_sent_to_review")
    assert ns, "in-app уведомления должны создаваться"
    assert all(n.email_state is None for n in ns)


# --- Лента и прочтение (FR-137) ---

def test_feed_and_mark_read(env):
    """US-039 ш.3: лента только свои; прочтение индивидуально (FR-137)."""
    c = env["as_author"](); db = env["db"]
    role_id = uuid.UUID(env["role_author"]["id"])
    reviewer = _user_with_role(db, "Рецензент-9д", role_id)
    m = _mk_material(c, "Материал-9м", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")
    _dispatch(db)

    rc = _client_of(reviewer)
    feed = rc.get("/api/v1/notifications").json()
    assert feed["total"] >= 1
    assert feed["unread"] >= 1
    nid = feed["items"][0]["id"]

    # Чужое уведомление недоступно (FR-137): автор — инициатор
    # material_sent_to_review → своих уведомлений не имеет
    ac = env["as_author"]()
    other = ac.get("/api/v1/notifications").json()
    assert other["total"] == 0

    r = rc.post(f"/api/v1/notifications/{nid}:read")
    assert r.status_code == 200, r.text
    assert r.json()["read_at"] is not None
    feed2 = rc.get("/api/v1/notifications?unread_only=true").json()
    assert all(i["read_at"] is not None for i in feed2["items"]) or feed2["total"] == 0
    assert rc.get("/api/v1/notifications:unread-count").json()["unread"] == 0

    # Повторное :read — идемпотентно
    r2 = rc.post(f"/api/v1/notifications/{nid}:read")
    assert r2.status_code == 200


def test_mark_all_read(env):
    """POST /notifications:read-all (FR-137)."""
    c = env["as_author"](); db = env["db"]
    role_id = uuid.UUID(env["role_author"]["id"])
    reviewer = _user_with_role(db, "Рецензент-9е", role_id)
    m = _mk_material(c, "Материал-9н", env["group"]["id"], env["type"]["id"])
    _attach_ready_file(client=c, db=db, material_id=m["id"])
    _transition(c, m["id"], "in_review")
    _dispatch(db)

    rc = _client_of(reviewer)
    before = rc.get("/api/v1/notifications").json()
    assert before["unread"] >= 1
    r = rc.post("/api/v1/notifications:read-all")
    assert r.status_code == 200, r.text
    assert r.json()["marked"] == before["unread"]
    assert rc.get("/api/v1/notifications:unread-count").json()["unread"] == 0


# --- Триггеры (US-047, СА) ---

def test_triggers_requires_super(env):
    """GET /notification-triggers — только СА (US-047)."""
    r = env["as_author"]().get("/api/v1/notification-triggers")
    assert r.status_code == 403
    r = env["as_sa"]().get("/api/v1/notification-triggers")
    assert r.status_code == 200
    ets = {t["event_type"] for t in r.json()}
    assert "material_sent_to_review" in ets
    assert "status_changed" in ets


def test_trigger_update_audited(env):
    """PUT /notification-triggers/{et}: изменение + аудит settings.change (FR-140)."""
    from sqlalchemy import select as s

    sc = env["as_sa"]()
    r = sc.put("/api/v1/notification-triggers/status_changed", json={
        "enabled": True,
        "recipients": [{"type": "fact_author"}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    audit = list(db_audit(env))
    assert any(a["action"] == "settings.change"
               and a["details"].get("event_type") == "status_changed"
               for a in audit)


def db_audit(env):
    db = env["db"]
    rows = db.execute(select(models.AuditEntry).order_by(models.AuditEntry.id)).scalars().all()
    out = []
    for a in rows:
        out.append({
            "action": a.action,
            "object_id": str(a.object_id) if a.object_id else None,
            "details": a.details or {},
        })
    return out


def test_trigger_update_validation(env):
    """Некорректные получатели/событие — 400/404 (§12.2)."""
    sc = env["as_sa"]()
    r = sc.put("/api/v1/notification-triggers/unknown_event", json={
        "enabled": True, "recipients": [],
    })
    assert r.status_code == 404
    r = sc.put("/api/v1/notification-triggers/material_rejected", json={
        "enabled": True, "recipients": [{"type": "fact_editor"}],
    })
    assert r.status_code == 400
    r = sc.put("/api/v1/notification-triggers/material_rejected", json={
        "enabled": True, "recipients": [{"type": "role"}],  # без role_id
    })
    assert r.status_code == 400


# --- Деактивация → service_tasks (US-004 ш.4, FR-012) ---

def test_deactivation_creates_transfer_task(env):
    """Единственный носитель review в группе → service_task transfer_review_right."""
    c = env["as_author"](); db = env["db"]
    role_id = uuid.UUID(env["role_author"]["id"])
    # Рецензент-носитель review отсутствует: автор — единственный (роль «Автор»
    # с review из _grant). Но автор имеет право через роль на группе.
    sa = env["as_sa"]()

    # Деактивация автора СА
    r = sa.delete(f"/api/v1/users/{env['author'].user_id}")
    assert r.status_code == 200, r.text

    tasks = list(db.execute(
        select(models.ServiceTask).where(models.ServiceTask.task_type == "transfer_review_right")
    ).scalars().all())
    assert len(tasks) == 1
    payload = tasks[0].payload
    assert payload["group_id"] == env["group"]["id"]
    assert payload["permission"] == "review"
    assert payload["user_id"] == str(env["author"].user_id)
    assert tasks[0].closed_at is None


def test_deactivation_no_task_when_other_holders(env):
    """Есть другой носитель review → задачи нет (FR-012)."""
    c = env["as_author"](); db = env["db"]
    role_id = uuid.UUID(env["role_author"]["id"])
    _user_with_role(db, "Второй носитель-9", role_id)
    sa = env["as_sa"]()
    r = sa.delete(f"/api/v1/users/{env['author'].user_id}")
    assert r.status_code == 200, r.text
    tasks = list(db.execute(
        select(models.ServiceTask).where(models.ServiceTask.task_type == "transfer_review_right")
    ).scalars().all())
    assert len(tasks) == 0


def test_deactivation_twice_no_dup_task(env):
    """Повторная деактивация (после активации) — без дубля открытой задачи."""
    c = env["as_author"](); db = env["db"]
    sa = env["as_sa"]()
    uid = env["author"].user_id
    r = sa.delete(f"/api/v1/users/{uid}")
    assert r.status_code == 200, r.text
    # повторно: still deactivated — was_active=False → задач не добавляется
    r = sa.delete(f"/api/v1/users/{uid}")
    assert r.status_code == 200, r.text
    tasks = list(db.execute(
        select(models.ServiceTask).where(models.ServiceTask.task_type == "transfer_review_right")
    ).scalars().all())
    assert len(tasks) == 1  # дубля нет


# --- file_blocked: прямое уведомление (FR-058, §8.1) ---

def test_file_blocked_direct_notification(env):
    """_notify_file_blocked: автор материала + все СА; вне триггеров."""
    from app.worker.tasks import _notify_file_blocked

    db = env["db"]
    c = env["as_author"]()
    m = _mk_material(c, "Материал-9п", env["group"]["id"], env["type"]["id"])
    fo = _attach_ready_file(client=c, db=db, material_id=m["id"])

    # Прямое уведомление: _notify_file_blocked использует get_session_factory
    # из app.worker.tasks — подменяем на тестовую сессию
    import app.worker.tasks as tasks_mod

    class _FakeFactory:
        def __call__(self):
            return db

    orig = tasks_mod.get_session_factory
    tasks_mod.get_session_factory = lambda: _FakeFactory()
    try:
        _notify_file_blocked(fo)
    finally:
        tasks_mod.get_session_factory = orig
    ns = _notifs(db, event_type="file_blocked")
    uids = {str(n.recipient_id) for n in ns}
    assert str(env["author"].user_id) in uids
    assert str(_SA_PRINCIPAL_ETAP9.user_id) in uids
    # dedup_key формат (§8.2)
    assert all(n.dedup_key == f"file_blocked:{fo.id}:{n.recipient_id}" for n in ns)
