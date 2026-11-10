# Тесты этапа 7: мастер-подчинённый (LLD §4.3, 7.10, §2.3; US-024–028, US-038).
# Паттерн test_files_versions.py: сид матрицы прямой вставкой (тестовая БД из
# моделей), СА через client, обычные пользователи через _client_of.
import uuid

from sqlalchemy import select

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db import models
from app.main import app


# --- Сид матрицы §2.6 (как этап 5/6) ---

_MATRIX_SEED = [
    ("draft", "in_review", False, ["edit"]),
    ("in_review", "approved", False, ["review"]),
    ("in_review", "draft", False, ["review", "edit"]),
    ("approved", "draft", False, ["review"]),
    ("approved", "published", True, ["publish"]),
    (None, "archived", True, ["archive"]),
]


def _seed_transition_matrix(db):
    if db.execute(select(models.TransitionRule)).scalars().first() is not None:
        return
    for from_status, to_status, is_protected, perms in _MATRIX_SEED:
        rule = models.TransitionRule(
            from_status=from_status, to_status=to_status, is_protected=is_protected
        )
        for p in perms:
            rule.permissions.append(models.TransitionRulePermission(
                permission=models.PermissionCode(p)
            ))
        db.add(rule)
    db.commit()


def _mk_group(client, name, parent_id=None):
    r = client.post("/api/v1/groups", json={"name": name, "parent_id": parent_id})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_type(client, name="Тип"):
    r = client.post("/api/v1/types", json={"name": name, "attribute_ids": []})
    assert r.status_code == 201, r.text
    return r.json()


def _get_role(client, name):
    body = client.get("/api/v1/roles").json()
    items = body["items"] if isinstance(body, dict) else body
    return next(x for x in items if x["name"] == name)


_SA_PRINCIPAL = None  # ленивый СА-principal для подмены в _grant


def _grant(client, group_id, role_id, perms):
    """Назначение снапшота прав — только СА; client фикстуры может быть автором,
    поэтому на время запроса подменяем principal на СА (тот же db-сеанс)."""
    global _SA_PRINCIPAL
    from app.api.deps import get_current_user as _gcu
    from app.main import app as _app
    from tests.conftest import _make_principal

    if _SA_PRINCIPAL is None:
        db = getattr(client, "_db", None)
        # db недоступен через client — principal создаётся в env-фикстуре ниже
        raise RuntimeError("_SA_PRINCIPAL не инициализирован")

    saved = _app.dependency_overrides.get(_gcu)
    _app.dependency_overrides[_gcu] = lambda: _SA_PRINCIPAL
    try:
        r = client.post(f"/api/v1/groups/{group_id}/permissions", json={
            "role_id": role_id,
            "entries": [{"permission": p, "state": "allow"} for p in perms],
        })
    finally:
        _app.dependency_overrides.pop(_gcu, None)
        if saved is not None:
            _app.dependency_overrides[_gcu] = saved
    assert r.status_code == 201, r.text


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


def _mk_language(db):
    """Атрибут «Язык» (стартовый набор, FR-046) + справочник со значениями."""
    d = models.Dictionary(name="Языки")
    db.add(d)
    db.flush()
    vals = {}
    for v in ("Русский", "English"):
        dv = models.DictionaryValue(dictionary_id=d.id, value=v)
        db.add(dv)
        vals[v] = dv
    a = models.Attribute(
        name="Язык", value_type=models.AttrValueType.dictionary,
        is_multivalue=False, dictionary_id=d.id,
    )
    db.add(a)
    db.commit()
    return a, vals


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _attach_ready_file(client, db, material_id, name="doc.png"):
    """Загрузка файла с заглушкой silo + scan_state=ready (конвейер — этап 6)."""
    from app.use_cases.files import silo

    r = client.post(
        f"/api/v1/materials/{material_id}/file",
        files={"file": (name, PNG_BYTES, "image/png")},
    )
    assert r.status_code == 200, r.text
    fo = db.execute(
        select(models.FileObject).where(
            models.FileObject.id == uuid.UUID(r.json()["file_state"]["file_id"])
        )
    ).scalar_one()
    fo.scan_state = "ready"
    db.commit()
    return fo


@pytest.fixture()
def env(client, db, monkeypatch):
    """СА + автор (edit/review/publish/copy/move/download) в двух группах."""
    global _SA_PRINCIPAL
    from app.use_cases.files import silo
    from tests.conftest import _make_principal

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)
    _SA_PRINCIPAL = _make_principal(db, "СА Этапа 7", is_super=True)
    _seed_transition_matrix(db)
    group1 = _mk_group(client, "Группа-7а")
    group2 = _mk_group(client, "Группа-7б")
    t = _mk_type(client, "Тип-7")
    role_author = _get_role(client, "Автор")
    _grant(client, group1["id"], role_author["id"],
           ["view", "create", "edit", "delete", "download", "copy", "move",
            "review", "publish"])
    _grant(client, group2["id"], role_author["id"],
           ["view", "create", "edit", "delete", "download", "copy", "move",
            "review", "publish"])
    author = _user_with_role(db, "Автор Этапа 7", uuid.UUID(role_author["id"]))
    c = _client_of(author)
    sa_client = _client_of(_SA_PRINCIPAL)

    r = c.post("/api/v1/materials", json={
        "name": "Мастер-инструкция", "group_id": group1["id"],
        "type_id": t["id"], "text_content": "Текст мастера",
    })
    assert r.status_code == 201, r.text
    master = r.json()

    # Мастер → approved (нужно для создания подчинённых); файл обязателен (FR-076)
    _attach_ready_file(client, db, master["id"])
    _transition(c, master["id"], "in_review")
    approved = _transition(c, master["id"], "approved")

    yield {
        "client": c, "db": db, "author": author, "sa": sa_client,
        "group1": group1, "group2": group2, "type": t,
        "master": master,
        "master_version": approved["version"],
    }
    app.dependency_overrides.pop(get_current_user, None)


def _mk_child(env, name="Подчинённый", group=None, via_api=True):
    c = env["client"]
    r = c.post(f"/api/v1/materials/{env['master']['id']}/children", json={
        "kind": "adaptation", "group_id": (group or env["group1"])["id"],
        "name": name,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, material_id, to_status, version=None, confirm_cascade=False):
    """Переход статуса с If-Match (FR-095); возвращает (response, body)."""
    if version is None:
        version = c.get(f"/api/v1/materials/{material_id}").json()["version"]
    body = {"to_status": to_status, "confirm_cascade": confirm_cascade}
    r = c.post(f"/api/v1/materials/{material_id}/transitions", json=body,
               headers={"If-Match": f'"{version}"'})
    assert r.status_code == 200, r.text
    return r.json()


# --- US-024: создание подчинённого (адаптация) ---

def test_create_child_adaptation(env):
    """US-024: черновик, копия текста/типа/тегов, master_id, независимость."""
    c, db = env["client"], env["db"]
    child = _mk_child(env)
    assert child["status"] == "draft"
    assert child["group_id"] == env["group1"]["id"]

    # master_id установлен; карточка мастера содержит подчинённого (FR-126)
    card = c.get(f"/api/v1/materials/{env['master']['id']}").json()
    assert any(x["id"] == child["id"] for x in card["children"])
    child_card = c.get(f"/api/v1/materials/{child['id']}").json()
    assert child_card["master_id"] == env["master"]["id"]
    assert child_card["master"]["name"] == "Мастер-инструкция"

    # Копия текста и типа
    assert child_card["text_content"] == "Текст мастера"
    assert child_card["type_id"] == env["type"]["id"]

    # Логическая независимость: правка копии не затрагивает оригинал (FR-033)
    r = c.patch(f"/api/v1/materials/{child['id']}",
                json={"text_content": "Правка копии"},
                headers={"If-Match": f'"{child_card["version"]}"'})
    assert r.status_code == 200, r.text
    master_card = c.get(f"/api/v1/materials/{env['master']['id']}").json()
    assert master_card["text_content"] == "Текст мастера"


def test_create_child_default_name_and_counter(env):
    """US-024 шаг 4 (FR-035): «<имя> Адаптация», конфликт → «<имя> Адаптация (2)»."""
    c = env["client"]
    ch1 = _mk_child(env, name=None)
    assert ch1["name"] == "Мастер-инструкция Адаптация"
    ch2 = _mk_child(env, name=None)
    assert ch2["name"] == "Мастер-инструкция Адаптация (2)"


def test_create_child_master_draft_rejected(env):
    """A1 US-024: мастер не в «Утверждён»/«Публикация» → 409 MASTER_NOT_PUBLISHED."""
    c, db = env["client"], env["db"]
    # второй мастер оставляем в draft
    r = c.post("/api/v1/materials", json={
        "name": "Черновик-мастер", "group_id": env["group1"]["id"],
        "type_id": env["type"]["id"],
    })
    draft_id = r.json()["id"]
    r = c.post(f"/api/v1/materials/{draft_id}/children", json={
        "kind": "adaptation", "group_id": env["group1"]["id"],
    })
    assert r.status_code == 409
    assert r.json()["code"] == "MASTER_NOT_PUBLISHED"


def test_create_child_no_create_right(env):
    """A2 US-024: нет права create в целевой группе → 403.

    Мастер/подчинённый в approved виден носителям процессных прав (§3.2);
    берём пользователя с edit в group1 (видит), но без create в group2.
    """
    db = env["db"]
    child = _mk_child(env, name="Создан")
    # роль и снапшот создаёт СА: client фикстуры в env — автор
    role = env["sa"].post("/api/v1/roles", json={
        "name": "Редактор-7", "permissions": ["view", "edit"],
    }).json()
    editor = _user_with_role(db, "Редактор Этапа 7", uuid.UUID(role["id"]))
    _grant(env["sa"], env["group1"]["id"], role["id"], ["view", "edit"])

    r = _client_of(editor).post(
        f"/api/v1/materials/{child['id']}/children",
        json={"kind": "adaptation", "group_id": env["group2"]["id"]},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "ACCESS_DENIED"


# --- US-025: перевод ---

def test_create_translation(env):
    """US-025: язык в атрибут «Язык» (замена скопированного) + имя по умолчанию."""
    c, db = env["client"], env["db"]
    attr, vals = _mk_language(db)
    # атрибут не назначен типу — 16.1-115: значение записывается независимо
    r = c.post(f"/api/v1/materials/{env['master']['id']}/children", json={
        "kind": "translation", "group_id": env["group1"]["id"],
        "language_id": str(vals["English"].id),
    })
    assert r.status_code == 201, r.text
    tr = r.json()
    assert tr["name"] == "Мастер-инструкция (Перевод, ENG)"

    card = c.get(f"/api/v1/materials/{tr['id']}").json()
    # «осиротевшее» значение: атрибут не привязан к типу → readonly (FR-051/16.1-115)
    lang_vals = [a for a in card["attributes"] if a["name"] == "Язык"]
    assert len(lang_vals) == 1
    assert lang_vals[0]["readonly"] is True


def test_create_translation_without_language_rejected(env):
    """A1 US-025: язык не указан → нельзя завершить создание."""
    r = env["client"].post(
        f"/api/v1/materials/{env['master']['id']}/children",
        json={"kind": "translation", "group_id": env["group1"]["id"]},
    )
    assert r.status_code == 400


# --- US-026: смена мастера / отвязка ---

def test_change_master_and_detach(env):
    """US-026: смена на второй утверждённый мастер; отвязка → NULL."""
    c, db = env["client"], env["db"]
    m2 = c.post("/api/v1/materials", json={
        "name": "Второй мастер", "group_id": env["group1"]["id"],
        "type_id": env["type"]["id"], "text_content": "Т2",
    }).json()
    _attach_ready_file(c, db, m2["id"])
    _transition(c, m2['id'], "in_review")
    _transition(c, m2['id'], "approved")

    child = _mk_child(env)

    # Смена мастера
    r = c.post(f"/api/v1/materials/{child['id']}/master",
               json={"master_id": m2["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["master_id"] == m2["id"]

    # Уведомления не создаются (16.1-111): notification_events нет в этапе 7 —
    # проверяем отсутствие ошибки и факт аудита material.master_change
    db = env["db"]
    audits = db.execute(
        select(models.AuditEntry).where(models.AuditEntry.action == "material.master_change")
    ).scalars().all()
    assert any(a.object_id == uuid.UUID(child["id"]) for a in audits)

    # Отвязка
    r = c.delete(f"/api/v1/materials/{child['id']}/master")
    assert r.status_code == 200, r.text
    assert r.json()["master_id"] is None
    card = c.get(f"/api/v1/materials/{child['id']}").json()
    assert card["master_id"] is None
    assert card["master"] is None


def test_change_master_to_child_of_child_rejected(env):
    """FR-032: новый мастер — сам подчинённый → 409 (один уровень связи)."""
    c = env["client"]
    m2 = _mk_child(env, name="Подчинённый-2")  # m2 уже имеет мастера
    child = _mk_child(env, name="Хочет сменить")
    r = c.post(f"/api/v1/materials/{child['id']}/master", json={"master_id": m2["id"]})
    assert r.status_code == 409


def test_change_master_self_reference_rejected(env):
    """FR-032: самоссылка запрещена."""
    child = _mk_child(env)
    r = env["client"].post(
        f"/api/v1/materials/{child['id']}/master", json={"master_id": child["id"]}
    )
    assert r.status_code == 409


def test_change_master_published_child_requires_published_master(env):
    """FR-036: подчинённый в «Публикации» → новый мастер только «Публикация»."""
    c, db = env["client"], env["db"]
    m2 = c.post("/api/v1/materials", json={
        "name": "Мастер только утверждён", "group_id": env["group1"]["id"],
        "type_id": env["type"]["id"], "text_content": "Т3",
    }).json()
    _attach_ready_file(c, db, m2["id"])
    _transition(c, m2['id'], "in_review")
    _transition(c, m2['id'], "approved")

    child = _mk_child(env)
    # подчинённый → published: сначала мастер в published (FR-042)
    _transition(c, env['master']['id'], "published")
    _transition(c, child['id'], "in_review")
    _transition(c, child['id'], "approved")
    _transition(c, child['id'], "published")

    # теперь смена на m2 (approved, не published) → 409 MASTER_STATUS_LOCKED
    r = c.post(f"/api/v1/materials/{child['id']}/master", json={"master_id": m2["id"]})
    assert r.status_code == 409
    assert r.json()["code"] == "MASTER_STATUS_LOCKED"


# --- US-027: перемещение ---

def test_move_material(env):
    """US-027: перемещение подчинённого; права сохраняются, связь не меняется."""
    c = env["client"]
    child = _mk_child(env)
    r = c.post(f"/api/v1/materials/{child['id']}/move",
               json={"group_id": env["group2"]["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["group_id"] == env["group2"]["id"]
    card = c.get(f"/api/v1/materials/{child['id']}").json()
    assert card["master_id"] == env["master"]["id"]  # связь не изменилась


def test_move_master_with_children_rejected(env):
    """A2 US-027 (FR-037): мастер с неудалёнными подчинёнными не перемещается."""
    c = env["client"]
    _mk_child(env)  # у env.master теперь есть подчинённый
    r = c.post(f"/api/v1/materials/{env['master']['id']}/move",
               json={"group_id": env["group2"]["id"]})
    assert r.status_code == 409
    assert r.json()["code"] == "MASTER_HAS_CHILDREN"


def test_move_name_conflict_no_autorename(env):
    """A1 US-027 (16.1-66): конфликт имени — без автопереименования."""
    c = env["client"]
    child = _mk_child(env, name="Переезд")
    # в group2 заранее материал с тем же именем
    r = c.post("/api/v1/materials", json={
        "name": "Переезд", "group_id": env["group2"]["id"],
        "type_id": env["type"]["id"],
    })
    assert r.status_code == 201, r.text
    r = c.post(f"/api/v1/materials/{child['id']}/move",
               json={"group_id": env["group2"]["id"]})
    assert r.status_code == 409
    assert r.json()["code"] == "NAME_CONFLICT"


# --- US-028: копирование ---

def test_copy_material(env):
    """US-028: черновик «<имя> Копия», master_id сохраняется, подчинённые не копируются."""
    c = env["client"]
    child = _mk_child(env, name="Копируемый")
    r = c.post(f"/api/v1/materials/{child['id']}/copy",
               json={"group_id": env["group2"]["id"]})
    assert r.status_code == 201, r.text
    cp = r.json()
    assert cp["status"] == "draft"
    assert cp["name"] == "Копируемый Копия"
    assert cp["group_id"] == env["group2"]["id"]

    card = c.get(f"/api/v1/materials/{cp['id']}").json()
    assert card["master_id"] == env["master"]["id"]  # мастер не в архиве → сохранён
    assert card["text_content"] == "Текст мастера"


def test_copy_counter(env):
    """FR-092: конфликт → «X Копия (2)»."""
    c = env["client"]
    child = _mk_child(env, name="Копир-2")
    r1 = c.post(f"/api/v1/materials/{child['id']}/copy",
                json={"group_id": env["group1"]["id"]})
    assert r1.status_code == 201
    r2 = c.post(f"/api/v1/materials/{child['id']}/copy",
                json={"group_id": env["group1"]["id"]})
    assert r2.status_code == 201
    assert r2.json()["name"] == "Копир-2 Копия (2)"


def test_copy_of_archived_master_detaches(env):
    """FR-092/US-028 шаг 4: мастер исходника в архиве → копия самостоятельная."""
    c = env["client"]
    child = _mk_child(env, name="Архивный")

    # архивируем мастера (каскад заархивирует и подчинённого — FR-039)
    r = _transition(c, env['master']['id'], "archived", confirm_cascade=True)

    # копия заархивированного подчинённого: его мастер в архиве → master_id NULL
    r = c.post(f"/api/v1/materials/{child['id']}/copy",
               json={"group_id": env["group2"]["id"]})
    assert r.status_code == 201, r.text
    cp = r.json()
    assert cp["status"] == "draft"  # копия — всегда черновик
    card = c.get(f"/api/v1/materials/{cp['id']}").json()
    assert card["master_id"] is None


def test_copy_no_right(env):
    """FR-092: нет права copy → 403 (право «Копирование» требуется)."""
    db = env["db"]
    reader = _user_with_role(db, "Читатель Копия",
                             uuid.UUID(_get_role(env["client"], "Читатель")["id"]))
    child = _mk_child(env, name="Некопируемый")
    r = _client_of(reader).post(
        f"/api/v1/materials/{child['id']}/copy",
        json={"group_id": env["group1"]["id"]},
    )
    # Читатель не видит черновик (не автор, нет процессных прав) → 404 по FR-067
    assert r.status_code in (403, 404)


# --- US-038: комментарии ---

def test_comments_flow(env):
    """US-038: участник процесса добавляет; читатель читает, добавить не может."""
    c, db = env["client"], env["db"]
    child = _mk_child(env, name="С комментариями")
    # черновик: виден автору (env.author). Добавляем комментарий (автор).
    r = c.post(f"/api/v1/materials/{child['id']}/comments",
               json={"text": "Первый комментарий"})
    assert r.status_code == 201, r.text
    com1 = r.json()
    assert com1["text"] == "Первый комментарий"

    # Неизменяемость (FR-096): PATCH/DELETE на коллекции комментариев — 405
    # (маршрутов изменения нет; OpenAPI-проверка ниже)
    r = c.patch(f"/api/v1/materials/{child['id']}/comments", json={"text": "x"})
    assert r.status_code == 405
    r = c.delete(f"/api/v1/materials/{child['id']}/comments")
    assert r.status_code == 405
    spec = c.get("/api/v1/openapi.json").json()
    comment_paths = [p for p in spec["paths"] if "/comments" in p]
    assert not any("{comment_id}" in p or p.endswith("comments/{id}") for p in comment_paths)

    # Аудит comment.create (FR-096)
    audits = db.execute(
        select(models.AuditEntry).where(models.AuditEntry.action == "comment.create")
    ).scalars().all()
    assert any(a.object_id == uuid.UUID(child["id"]) for a in audits)

    # Чтение — тем, кому виден материал: автор читает
    r = c.get(f"/api/v1/materials/{child['id']}/comments")
    assert r.status_code == 200
    assert r.json()["total"] == 1

    # Читатель (не участник процесса): черновик невидим → 404 (FR-067/FR-097);
    # на опубликованном — читает, добавить не может (A1 US-038)
    _transition(c, env['master']['id'], "published")
    reader = _user_with_role(db, "Читатель Комментов",
                             uuid.UUID(_get_role(env["client"], "Читатель")["id"]))
    # Читателю нужен view на группу
    _grant(env["client"], env["group1"]["id"], _get_role(env["client"], "Читатель")["id"],
           ["view"])
    rc = _client_of(reader)
    r = rc.get(f"/api/v1/materials/{env['master']['id']}/comments")
    assert r.status_code == 200
    r = rc.post(f"/api/v1/materials/{env['master']['id']}/comments",
                json={"text": "не могу"})
    assert r.status_code == 403


def test_comment_empty_rejected(env):
    """Пустой комментарий → 400."""
    child = _mk_child(env, name="Пустой коммент")
    r = env["client"].post(
        f"/api/v1/materials/{child['id']}/comments", json={"text": "   "}
    )
    assert r.status_code == 400


# --- Инварианты §2.3 ---

def test_master_id_self_check(env):
    """CHECK master_id <> id (LLD §2.3): прямая вставка отклоняется БД."""
    db = env["db"]
    m = db.execute(
        select(models.Material).where(models.Material.is_deleted.is_(False))
    ).scalars().first()
    m.master_id = m.id
    with pytest.raises(Exception):
        db.flush()


def test_child_cannot_get_master_id(env):
    """FR-032/§2.3-1: материал, на который ссылаются, не получает master_id."""
    c, db = env["client"], env["db"]
    child = _mk_child(env, name="Уже ссылаются")
    # child виден; теперь другой материал не может выбрать child мастером
    # (у child нет собственного мастера, но у child есть master_id → он подчинённый)
    m2 = c.post("/api/v1/materials", json={
        "name": "Попытка", "group_id": env["group1"]["id"],
        "type_id": env["type"]["id"],
    }).json()
    _attach_ready_file(c, db, m2["id"])
    _transition(c, m2['id'], "in_review")
    _transition(c, m2['id'], "approved")
    r = c.post(f"/api/v1/materials/{m2['id']}/master", json={"master_id": child["id"]})
    assert r.status_code == 409




