# Этап 5: жизненный цикл — переходы по матрице (US-015–021), журнал (FR-075),
# CRUD матрицы СА (US-046), If-Match на переходах (US-054, FR-094/095).
# Права перехода проверяются сквозь API (единая семантика UI/API — FR-129).
# В тестах БД создаётся из моделей, поэтому сид матрицы §2.6 — прямая вставка
# (в live-стеке его делает миграция 0005).
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.api.deps import get_current_user
from app.db import models
from app.main import app


def func_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)

# Сид §2.6 (FR-071/073): (from_status, to_status, is_protected, permissions)
_SEED = [
    ("draft", "in_review", False, ["edit"]),
    ("in_review", "approved", False, ["review"]),
    ("in_review", "draft", False, ["review", "edit"]),
    ("approved", "draft", False, ["review"]),
    ("approved", "published", True, ["publish"]),
    (None, "archived", True, ["archive"]),
]


def _mk_group(client, name, parent_id=None):
    r = client.post("/api/v1/groups", json={"name": name, "parent_id": parent_id})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_type(client, name="Тип"):
    r = client.post("/api/v1/types", json={"name": name, "attribute_ids": []})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_material(client, name="Материал", group_id=None, type_id=None):
    r = client.post("/api/v1/materials", json={
        "name": name, "group_id": group_id, "type_id": type_id,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _grant(client, obj_type, obj_id, role_id, entries):
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
    from tests.conftest import _make_principal

    pr = _make_principal(db, name, is_super=False)
    db.add(models.UserRole(
        user_id=pr.user_id,
        role_id=role_id if isinstance(role_id, uuid.UUID) else uuid.UUID(role_id),
    ))
    db.commit()
    return pr


def _client_of(pr):
    app.dependency_overrides[get_current_user] = lambda: pr
    return TestClient(app)


def _release():
    app.dependency_overrides.pop(get_current_user, None)


def _set_status(db, material_id, status: str, **kw):
    """Прямая установка статуса/полей (загрузка файлов — этап 6)."""
    vals = {"status": models.MaterialStatus(status), **kw}
    db.execute(update(models.Material).where(models.Material.id == material_id).values(**vals))
    db.commit()


def _mk_file(db, sha="a" * 64, scan_state="ready"):
    fo = models.FileObject(
        cas_key=f"ab/{sha}", sha256=sha, filename="f.txt",
        mime_type="text/plain", size_bytes=3,
        scan_state=scan_state,
    )
    db.add(fo)
    db.commit()
    return fo


def _attach_file(db, material_id, file_id):
    db.execute(update(models.Material).where(models.Material.id == material_id)
               .values(current_file_id=file_id))
    db.commit()


def _rules(client):
    r = client.get("/api/v1/transition-rules")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def sa(client, db):
    """Клиент СА с сидом матрицы §2.6 (прямая вставка — как миграция 0005)."""
    for fs, ts, prot, perms in _SEED:
        db.add(models.TransitionRule(
            from_status=models.MaterialStatus(fs) if fs else None,
            to_status=models.MaterialStatus(ts),
            is_protected=prot,
            permissions=[
                models.TransitionRulePermission(permission=models.PermissionCode(p))
                for p in perms
            ],
        ))
    db.commit()
    return client


# --- US-046: CRUD матрицы (СА) ---

def test_seed_matrix_visible_to_sa(sa):
    """US-046 шаг 1: СА видит предустановленную матрицу с правами переходов."""
    rules = _rules(sa)
    pairs = {(r["from_status"], r["to_status"]): r for r in rules}
    assert pairs[(None, "archived")]["is_protected"] is True
    assert pairs[(None, "archived")]["permissions"] == ["archive"]
    assert pairs[("approved", "published")]["is_protected"] is True
    assert pairs[("draft", "in_review")]["permissions"] == ["edit"]
    assert pairs[("in_review", "draft")]["permissions"] == ["edit", "review"]


def test_rules_forbidden_for_non_sa(client, db, as_user):
    """Матрица — только СА (US-046 актёры)."""
    c = as_user("Рядовой", is_super=False)
    r = c.get("/api/v1/transition-rules")
    assert r.status_code == 403
    r2 = c.post("/api/v1/transition-rules", json={
        "from_status": "draft", "to_status": "in_review", "permissions": ["edit"],
    })
    assert r2.status_code == 403
    _release()


def test_create_rule_and_archived_source(sa):
    """US-046: создание правила; from_status='archived' → 400 (FR-073)."""
    r = sa.post("/api/v1/transition-rules", json={
        "from_status": "draft", "to_status": "published", "permissions": ["publish"],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["from_status"] == "draft" and body["to_status"] == "published"

    r2 = sa.post("/api/v1/transition-rules", json={
        "from_status": "archived", "to_status": "draft", "permissions": ["edit"],
    })
    assert r2.status_code == 400, r2.text
    assert r2.json()["code"] == "ARCHIVED_SOURCE_RULE_FORBIDDEN"

    r3 = sa.post("/api/v1/transition-rules", json={
        "from_status": "draft", "to_status": "published", "permissions": ["publish"],
    })
    assert r3.status_code == 409  # UNIQUE (from_status, to_status)


def test_delete_rule_and_protection(sa):
    """US-046 шаги 3–4: незащищённое правило удаляется; защищённое — нет (FR-073)."""
    rules = _rules(sa)
    target = next(r for r in rules if r["from_status"] == "draft" and r["to_status"] == "in_review")
    r = sa.delete(f"/api/v1/transition-rules/{target['id']}")
    assert r.status_code == 204, r.text
    protected = next(r for r in rules if r["from_status"] == "approved" and r["to_status"] == "published")
    r2 = sa.delete(f"/api/v1/transition-rules/{protected['id']}")
    assert r2.status_code == 409
    wildcard = next(r for r in rules if r["from_status"] is None)
    r3 = sa.delete(f"/api/v1/transition-rules/{wildcard['id']}")
    assert r3.status_code == 409


def test_patch_rule_permissions(sa):
    """US-046 шаг 2: несколько прав на переход — достаточно любого (FR-070)."""
    rules = _rules(sa)
    target = next(r for r in rules if r["from_status"] == "approved" and r["to_status"] == "draft")
    r = sa.patch(f"/api/v1/transition-rules/{target['id']}", json={
        "permissions": ["review", "edit"],
    })
    assert r.status_code == 200, r.text
    assert sorted(r.json()["permissions"]) == ["edit", "review"]


# --- US-008 / US-015: отправка на проверку ---

def test_send_to_review_requires_file(sa, db):
    """US-008 шаг 3 / US-015 A1: без файла → 409 FILE_REQUIRED (FR-028/076)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-файл", group_id=root["id"], type_id=t["id"])
    r = sa.post(f"/api/v1/materials/{m['id']}/transitions", json={"to_status": "in_review"},
                headers={"If-Match": "1"})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "FILE_REQUIRED"


def test_send_to_review_ok_with_ready_file(sa, db):
    """US-015 основной поток: файл ready + право edit → in_review; журнал + ETag."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-ревью", group_id=root["id"], type_id=t["id"])
    fo = _mk_file(db)
    _attach_file(db, uuid.UUID(m["id"]), fo.id)

    r = sa.post(f"/api/v1/materials/{m['id']}/transitions", json={"to_status": "in_review"},
                headers={"If-Match": "1"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_review"
    assert r.json()["version"] == 2

    r2 = sa.get(f"/api/v1/materials/{m['id']}/status-log")
    assert r2.status_code == 200
    log = r2.json()
    assert len(log) == 1 and log[0]["from_status"] == "draft" and log[0]["to_status"] == "in_review"
    assert log[0]["user_display_name"]

    r3 = sa.get(f"/api/v1/materials/{m['id']}")
    assert r3.headers.get("etag") == '"2"'


def test_file_not_ready_blocks_transition(sa, db):
    """US-015 A1: scan_state != ready → 409 FILE_NOT_READY (FR-058)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-скан", group_id=root["id"], type_id=t["id"])
    fo = _mk_file(db, scan_state="scanning")
    _attach_file(db, uuid.UUID(m["id"]), fo.id)
    r = sa.post(f"/api/v1/materials/{m['id']}/transitions", json={"to_status": "in_review"},
                headers={"If-Match": "1"})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "FILE_NOT_READY"


# --- Права перехода (FR-070–072) ---

def test_transition_rights_from_matrix(sa, db):
    """US-015 A2 / US-020 A2: право перехода — по матрице; без права — только СА (FR-072)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-права", group_id=root["id"], type_id=t["id"])
    fo = _mk_file(db)
    _attach_file(db, uuid.UUID(m["id"]), fo.id)
    mid = uuid.UUID(m["id"])

    author_role = _get_role(sa, "Автор")
    _grant(sa, "group", root["id"], author_role["id"],
           [{"permission": "view", "state": "allow"}, {"permission": "edit", "state": "allow"}])
    pr = _user_with_role(db, "Автор Петров", author_role["id"])
    c = _client_of(pr)
    try:
        r = c.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "in_review"},
                   headers={"If-Match": "1"})
        assert r.status_code == 200, r.text

        r2 = c.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "approved"},
                    headers={"If-Match": "2"})
        assert r2.status_code == 409
        assert r2.json()["code"] == "TRANSITION_NOT_ALLOWED"

        r3 = c.get(f"/api/v1/materials/{mid}/transitions")
        assert r3.status_code == 200
        tr = {x["to_status"]: x for x in r3.json()}
        assert tr["approved"]["allowed"] is False
        assert tr["draft"]["allowed"] is True  # in_review→draft: review ИЛИ edit
    finally:
        _release()


def test_transition_any_of_permissions(sa, db):
    """US-046 шаг 2: на переходе несколько прав — достаточно любого (FR-070)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-любое", group_id=root["id"], type_id=t["id"])
    fo = _mk_file(db)
    _attach_file(db, uuid.UUID(m["id"]), fo.id)
    mid = uuid.UUID(m["id"])

    author_role = _get_role(sa, "Автор")
    _grant(sa, "group", root["id"], author_role["id"],
           [{"permission": "view", "state": "allow"}, {"permission": "edit", "state": "allow"}])
    pr = _user_with_role(db, "Автор Второй", author_role["id"])
    c = _client_of(pr)
    try:
        r = sa.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "in_review"},
                    headers={"If-Match": "1"})
        assert r.status_code == 200
        # in_review→draft: review или edit; у автора только edit — достаточно (FR-070)
        r2 = c.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "draft"},
                    headers={"If-Match": "2"})
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "draft"
    finally:
        _release()


def test_approve_sets_signatory(sa, db):
    """US-016: утверждение фиксирует подписанта и дату (FR-068)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-утв", group_id=root["id"], type_id=t["id"])
    fo = _mk_file(db)
    _attach_file(db, uuid.UUID(m["id"]), fo.id)
    mid = uuid.UUID(m["id"])

    reviewer_role = _get_role(sa, "Рецензент")
    _grant(sa, "group", root["id"], reviewer_role["id"],
           [{"permission": "view", "state": "allow"}, {"permission": "review", "state": "allow"}])
    pr = _user_with_role(db, "Рецензент Сидоров", reviewer_role["id"])

    sa.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "in_review"},
            headers={"If-Match": "1"})

    c = _client_of(pr)
    try:
        r = c.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "approved"},
                   headers={"If-Match": "2"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "approved" and body["signatory_id"] == str(pr.user_id)
        assert body["signatory_at"]

        log = sa.get(f"/api/v1/materials/{mid}/status-log").json()
        assert [(x["from_status"], x["to_status"]) for x in log] == [
            ("draft", "in_review"), ("in_review", "approved"),
        ]
    finally:
        _release()


def test_withdraw_approval_clears_signatory(sa, db):
    """US-019: отзыв утверждения → draft, подписант очищается (FR-082)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-отзыв", group_id=root["id"], type_id=t["id"])
    fo = _mk_file(db)
    _attach_file(db, uuid.UUID(m["id"]), fo.id)
    mid = uuid.UUID(m["id"])

    sa.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "in_review"},
            headers={"If-Match": "1"})
    sa.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "approved"},
            headers={"If-Match": "2"})
    r = sa.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "draft"},
                headers={"If-Match": "3"})
    assert r.status_code == 200, r.text
    assert r.json()["signatory_id"] is None  # FR-082


def test_publish_sets_published_at(sa, db):
    """US-020: публикация фиксирует дату (FR-086); читатель видит (FR-066)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-публ", group_id=root["id"], type_id=t["id"])
    fo = _mk_file(db)
    _attach_file(db, uuid.UUID(m["id"]), fo.id)
    mid = uuid.UUID(m["id"])

    for st, v in (("in_review", "1"), ("approved", "2"), ("published", "3")):
        r = sa.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": st},
                    headers={"If-Match": v})
        assert r.status_code == 200, r.text
    assert r.json()["published_at"]

    reader_role = _get_role(sa, "Читатель")
    _grant(sa, "group", root["id"], reader_role["id"], [{"permission": "view", "state": "allow"}])
    pr = _user_with_role(db, "Читатель Один", reader_role["id"])
    c = _client_of(pr)
    try:
        assert c.get(f"/api/v1/materials/{mid}").status_code == 200
        tr = c.get(f"/api/v1/materials/{mid}/transitions").json()
        assert all(x["allowed"] is False for x in tr)  # нет прав процесса (FR-072)
    finally:
        _release()


# --- US-021: архивация и каскад ---

def test_archive_from_any_status_no_file_needed(sa, db):
    """US-021: «* → Архив» — из любого статуса; файл не требуется (FR-076)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-арх", group_id=root["id"], type_id=t["id"])  # без файла
    r = sa.post(f"/api/v1/materials/{m['id']}/transitions", json={"to_status": "archived"},
                headers={"If-Match": "1"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "archived" and r.json()["archived_at"]

    r2 = sa.post(f"/api/v1/materials/{m['id']}/transitions", json={"to_status": "draft"},
                 headers={"If-Match": "2"})
    assert r2.status_code == 409
    assert r2.json()["code"] == "TRANSITION_NOT_ALLOWED"  # финальный статус (FR-087)

    # Из архива список доступных переходов пуст (FR-087: архив финален)
    tr = sa.get(f"/api/v1/materials/{m['id']}/transitions").json()
    assert tr == []


def test_archive_cascade_requires_confirm(sa, db):
    """US-021 шаги 4–5: каскад — после подтверждения; children_count в ошибке (FR-039)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    master = _mk_material(sa, "Мастер", group_id=root["id"], type_id=t["id"])
    child = _mk_material(sa, "Подчинённый", group_id=root["id"], type_id=t["id"])
    db.execute(update(models.Material).where(models.Material.id == uuid.UUID(child["id"]))
               .values(master_id=uuid.UUID(master["id"])))
    db.commit()

    r = sa.post(f"/api/v1/materials/{master['id']}/transitions", json={"to_status": "archived"},
                headers={"If-Match": "1"})
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "CASCADE_CONFIRM_REQUIRED"
    assert body["params"]["children_count"] == 1

    r2 = sa.post(f"/api/v1/materials/{master['id']}/transitions", json={
        "to_status": "archived", "confirm_cascade": True,
    }, headers={"If-Match": "1"})
    assert r2.status_code == 200, r2.text
    assert sorted(r2.json()["cascade_archived"]) == [child["id"]]
    log_m = sa.get(f"/api/v1/materials/{master['id']}/status-log").json()
    log_c = sa.get(f"/api/v1/materials/{child['id']}/status-log").json()
    assert log_m[0]["to_status"] == "archived" and log_c[0]["to_status"] == "archived"
    cm = sa.get(f"/api/v1/materials/{master['id']}")
    cc = sa.get(f"/api/v1/materials/{child['id']}")
    assert cm.json()["version"] == 2 and cc.json()["version"] == 2


def test_master_locked_with_published_children(sa, db):
    """FR-041: мастер с подчинёнными в «Публикации» — только → Архив."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    master = _mk_material(sa, "Мастер-лок", group_id=root["id"], type_id=t["id"])
    child = _mk_material(sa, "Адаптация", group_id=root["id"], type_id=t["id"])
    mid, cid = uuid.UUID(master["id"]), uuid.UUID(child["id"])
    db.execute(update(models.Material).where(models.Material.id == cid).values(master_id=mid))
    # Мастер approved (из published нет исходящих правил — валидатор 5 не достигался бы);
    # подчинённый — published (FR-041: с подчинёнными в «Публикации»)
    db.execute(update(models.Material).where(models.Material.id == mid)
               .values(status=models.MaterialStatus.approved))
    db.execute(update(models.Material).where(models.Material.id == cid)
               .values(status=models.MaterialStatus.published))
    db.commit()

    r = sa.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "draft"},
                headers={"If-Match": "1"})
    assert r.status_code == 409
    assert r.json()["code"] == "MASTER_STATUS_LOCKED"

    r2 = sa.post(f"/api/v1/materials/{mid}/transitions", json={
        "to_status": "archived", "confirm_cascade": True,
    }, headers={"If-Match": "1"})
    assert r2.status_code == 200, r2.text


def test_child_not_published_before_master(sa, db):
    """FR-042: подчинённый не публикуется раньше мастера."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    master = _mk_material(sa, "Мастер-рано", group_id=root["id"], type_id=t["id"])
    child = _mk_material(sa, "Адаптация-рано", group_id=root["id"], type_id=t["id"])
    mid, cid = uuid.UUID(master["id"]), uuid.UUID(child["id"])
    db.execute(update(models.Material).where(models.Material.id == cid).values(master_id=mid))
    db.execute(update(models.Material).where(models.Material.id == mid)
               .values(status=models.MaterialStatus.approved, current_file_id=_mk_file(db).id))
    db.execute(update(models.Material).where(models.Material.id == cid)
               .values(status=models.MaterialStatus.approved, current_file_id=_mk_file(db, sha="b" * 64).id))
    db.commit()

    r = sa.post(f"/api/v1/materials/{cid}/transitions", json={"to_status": "published"},
                headers={"If-Match": "1"})
    assert r.status_code == 409
    assert r.json()["code"] == "MASTER_NOT_PUBLISHED"

    r2 = sa.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "published"},
                 headers={"If-Match": "1"})
    assert r2.status_code == 200, r2.text
    r3 = sa.post(f"/api/v1/materials/{cid}/transitions", json={"to_status": "published"},
                 headers={"If-Match": "1"})
    assert r3.status_code == 200, r3.text


# --- US-054 / US-010: If-Match ---

def test_if_match_required_and_conflict(sa, db):
    """US-054: без If-Match — 428; неактуальный — 412 (FR-094/095)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-etag", group_id=root["id"], type_id=t["id"])
    mid = uuid.UUID(m["id"])

    r = sa.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "in_review"})
    assert r.status_code == 428  # FR-095

    r2 = sa.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "in_review"},
                 headers={"If-Match": "999"})
    assert r2.status_code == 412

    # Валидаторы после версии: актуальная версия, но нет файла → FILE_REQUIRED
    r3 = sa.post(f"/api/v1/materials/{mid}/transitions", json={"to_status": "in_review"},
                 headers={"If-Match": "1"})
    assert r3.status_code == 409 and r3.json()["code"] == "FILE_REQUIRED"


def test_status_log_requires_visibility(sa, db, as_user):
    """§12.3: журнал — при видимости материала; невидим = 404 (FR-067)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-журн", group_id=root["id"], type_id=t["id"])
    c = as_user("Чужой", is_super=False)
    r = c.get(f"/api/v1/materials/{m['id']}/status-log")
    assert r.status_code == 404
    _release()


def test_sa_bypasses_transition_rights(sa, db):
    """FR-104: СА проходит переход без назначенных прав; обычный — нет (FR-072)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-са", group_id=root["id"], type_id=t["id"])
    fo = _mk_file(db)
    _attach_file(db, uuid.UUID(m["id"]), fo.id)

    r = sa.post("/api/v1/transition-rules", json={
        "from_status": "draft", "to_status": "published", "permissions": [],
    })
    assert r.status_code == 200

    r2 = sa.post(f"/api/v1/materials/{m['id']}/transitions", json={"to_status": "published"},
                 headers={"If-Match": "1"})
    assert r2.status_code == 200, r2.text  # СА в обход (FR-104)

    reader_role = _get_role(sa, "Читатель")
    _grant(sa, "group", root["id"], reader_role["id"], [{"permission": "view", "state": "allow"}])
    pr = _user_with_role(db, "Читатель Два", reader_role["id"])
    c = _client_of(pr)
    try:
        r3 = c.post(f"/api/v1/materials/{m['id']}/transitions", json={"to_status": "published"},
                    headers={"If-Match": "2"})
        assert r3.status_code == 409
        assert r3.json()["code"] == "TRANSITION_NOT_ALLOWED"
    finally:
        _release()


def test_audit_entries_written(sa, db):
    """§4.1 фиксация + US-046 шаг 5: audit_entries пишутся (append-only, §11)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-аудит", group_id=root["id"], type_id=t["id"])
    fo = _mk_file(db)
    _attach_file(db, uuid.UUID(m["id"]), fo.id)
    sa.post(f"/api/v1/materials/{uuid.UUID(m['id'])}/transitions",
            json={"to_status": "in_review"}, headers={"If-Match": "1"})
    rules = _rules(sa)
    target = next(x for x in rules if x["from_status"] == "draft" and x["to_status"] == "in_review")
    sa.delete(f"/api/v1/transition-rules/{target['id']}")

    rows = db.query(models.AuditEntry).order_by(models.AuditEntry.id).all()
    actions = [r.action for r in rows]
    # Этап 10 (US-049, FR-140): создание материала теперь тоже в журнале
    assert "material.create" in actions
    assert "material.status_change" in actions
    assert "transition_matrix.change" in actions
    status_row = next(r for r in rows if r.action == "material.status_change")
    assert status_row.details["from"] == "draft"


# --- §4.2: правки по статусам (US-009; файл — этап 6, здесь — текст) ---

def _patch_text(client, m, text, version):
    return client.patch(f"/api/v1/materials/{m['id']}", json={"text_content": text},
                        headers={"If-Match": str(version)})


def test_edit_in_published_downgrades_to_draft(sa, db):
    """US-009 шаг 3: правка контента в published → draft, очистка подписанта (FR-084)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-даунгрейд", group_id=root["id"], type_id=t["id"])
    mid = uuid.UUID(m["id"])
    from tests.conftest import _make_principal

    pr = _make_principal(db, "СА-тест", is_super=True)
    db.execute(update(models.Material).where(models.Material.id == mid)
               .values(status=models.MaterialStatus.published,
                       signatory_id=pr.user_id,
                       signatory_at=func_now()))
    db.commit()

    r = _patch_text(sa, m, "Новый текст", 1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 2

    card = sa.get(f"/api/v1/materials/{mid}").json()
    assert card["status"] == "draft"

    log = sa.get(f"/api/v1/materials/{mid}/status-log").json()
    assert [("published", "draft")] == [(x["from_status"], x["to_status"]) for x in log]


def test_edit_in_review_keeps_status(sa, db):
    """US-009 шаг 2: правка контента в in_review сохраняет статус (FR-085)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-на-ревью", group_id=root["id"], type_id=t["id"])
    mid = uuid.UUID(m["id"])
    db.execute(update(models.Material).where(models.Material.id == mid)
               .values(status=models.MaterialStatus.in_review))
    db.commit()

    r = _patch_text(sa, m, "Правка на ревью", 1)
    assert r.status_code == 200, r.text
    card = sa.get(f"/api/v1/materials/{mid}").json()
    assert card["status"] == "in_review"  # статус сохранён
    assert card["version"] == 2

    rows = db.query(models.AuditEntry).filter(
        models.AuditEntry.action == "material.update",
        models.AuditEntry.object_id == mid,
    ).all()
    assert any((r.details or {}).get("on_review") for r in rows)


def test_edit_metadata_does_not_change_status(sa, db):
    """US-009 шаг 3: правка только метаданных статусы не снимает никогда (FR-084)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-мета", group_id=root["id"], type_id=t["id"])
    mid = uuid.UUID(m["id"])
    db.execute(update(models.Material).where(models.Material.id == mid)
               .values(status=models.MaterialStatus.published))
    db.commit()

    r = sa.patch(f"/api/v1/materials/{mid}", json={"name": "М-мета-2"},
                 headers={"If-Match": "1"})
    assert r.status_code == 200, r.text
    card = sa.get(f"/api/v1/materials/{mid}").json()
    assert card["status"] == "published"  # статус не снят
    assert card["name"] == "М-мета-2"


def test_edit_in_archived_forbidden(sa, db):
    """US-009 шаг 4: в архиве редактирование запрещено (FR-087) — 403."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    m = _mk_material(sa, "М-арх-ред", group_id=root["id"], type_id=t["id"])
    mid = uuid.UUID(m["id"])
    db.execute(update(models.Material).where(models.Material.id == mid)
               .values(status=models.MaterialStatus.archived))
    db.commit()

    r = _patch_text(sa, m, "Х", 1)
    assert r.status_code == 403
    r2 = sa.patch(f"/api/v1/materials/{mid}", json={"name": "Х"},
                  headers={"If-Match": "1"})
    assert r2.status_code == 403


def test_edit_master_with_published_children_blocked(sa, db):
    """US-009 A1: правка контента мастера с подчинёнными в published блокируется (FR-041)."""
    root = _mk_group(sa, "Отдел")
    t = _mk_type(sa)
    master = _mk_material(sa, "Мастер-блок", group_id=root["id"], type_id=t["id"])
    child = _mk_material(sa, "Подчинённый-блок", group_id=root["id"], type_id=t["id"])
    mid, cid = uuid.UUID(master["id"]), uuid.UUID(child["id"])
    db.execute(update(models.Material).where(models.Material.id == cid).values(master_id=mid))
    db.execute(update(models.Material).where(models.Material.id == mid)
               .values(status=models.MaterialStatus.published))
    db.execute(update(models.Material).where(models.Material.id == cid)
               .values(status=models.MaterialStatus.published))
    db.commit()

    r = _patch_text(sa, master, "Новый текст", 1)
    assert r.status_code == 409
    assert r.json()["code"] == "MASTER_STATUS_LOCKED"

    # Правка метаданных разрешена (FR-041, §4.2)
    r2 = sa.patch(f"/api/v1/materials/{mid}", json={"name": "Мастер-блок-2"},
                  headers={"If-Match": "1"})
    assert r2.status_code == 200, r2.text
