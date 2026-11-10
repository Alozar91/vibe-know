# Тесты этапа 6: файлы и версии (LLD §5–6, §9).
# Конвейер (worker/Celery/silo) в тестах недоступен — заглушка silo monkeypatch'ем;
# state-машина файла проверяется вызовами обработчиков задач напрямую.
import uuid

from sqlalchemy import select

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db import models
from app.main import app


@pytest.fixture()
def mat(client, db, as_user):
    """Группа + тип + материал от имени автора с ролью «Автор» и снапшотом прав."""
    from app.api.deps import get_current_user
    from app.main import app

    _seed_transition_matrix(db)

    # СА создаёт группу/тип/снапшот (client фикстуры — СА)
    group = _mk_group(client, "Группа-6")
    t = _mk_type(client, "Тип-6")
    role_author = _get_role(client, "Автор")

    r = client.post(f"/api/v1/groups/{group['id']}/permissions", json={
        "role_id": role_author["id"],
        "entries": [
            {"permission": "view", "state": "allow"},
            {"permission": "create", "state": "allow"},
            {"permission": "edit", "state": "allow"},
            {"permission": "delete", "state": "allow"},
            {"permission": "download", "state": "allow"},
        ],
    })
    assert r.status_code == 201, r.text

    # автор — обычный пользователь с ролью Автор
    author = _user_with_role(db, "Автор Этапа 6", uuid.UUID(role_author["id"]))
    c = _client_of(author)

    r = c.post("/api/v1/materials", json={
        "name": "Материал с файлом", "group_id": group["id"],
        "type_id": t["id"], "text_content": "",
    })
    assert r.status_code == 201, r.text
    mid = r.json()["id"]

    yield {"id": mid, "group_id": group["id"], "type_id": t["id"], "client": c,
           "author": author}
    app.dependency_overrides.pop(get_current_user, None)


# Сид §2.6 (в live-стеке — миграция 0005; тестовая БД создаётся из моделей)
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
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: pr
    return TestClient(app)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64
MD_TEXT = "# Инструкция\n\nТекст инструкции.\n"


def test_upload_creates_file_and_version1(mat, client, db, monkeypatch):
    """US-007 шаг 6: файл привязан, version 1 фиксируется; scan поставлен в очередь."""
    from app.db import models
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)

    r = client.post(
        f"/api/v1/materials/{mat['id']}/file",
        files={"file": ("doc.md", MD_TEXT, "text/markdown")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file_state"]["scan_state"] == "pending_scan"
    assert body["text_filled_automatically"] is True  # 16.1-110

    # system_tasks: задача antivirus queued
    tasks = db.execute(select(models.SystemTask)).scalars().all()
    assert any(t.task_type == "antivirus" and t.state == "queued" for t in tasks)

    # version 1 зафиксирована при создании (без файла), версия 2 — после файла?
    # Материал создан пустышкой (версия 1), загрузка файла — версия 2 (file_id появился)
    vs = client.get(f"/api/v1/materials/{mat['id']}/versions").json()
    assert vs["total"] == 2
    assert vs["items"][0]["number"] == 2  # desc


def test_upload_dedup_same_content(mat, client, db, monkeypatch):
    """§6.2: повторная загрузка того же содержимого → тот же FileObject (дедуп)."""
    from app.db import models
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)

    client.post(f"/api/v1/materials/{mat['id']}/file",
                files={"file": ("a.md", MD_TEXT, "text/markdown")})
    # делаем ready вручную (заглушка worker в тестах не работает)
    fo = db.execute(select(models.FileObject)).scalars().first()
    fo.scan_state = "ready"
    db.commit()

    r = client.post(f"/api/v1/materials/{mat['id']}/file",
                    files={"file": ("a2.md", MD_TEXT, "text/markdown")})
    assert r.status_code == 200
    st = r.json()["file_state"]
    assert st["file_id"] == str(fo.id)  # тот же объект
    # ref_count = 1 (первая привязка) + 1 (вторая) = 2
    db.refresh(fo)
    assert fo.ref_count == 2


def test_upload_infected_and_pending(mat, client, db, monkeypatch):
    """§6.2: повторная загрузка того же содержимого при pending_scan → FILE_PENDING_SCAN;
    при infected → FILE_BLOCKED (привязка невозможна, загрузка не выполняется)."""
    from app.db import models
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)

    client.post(f"/api/v1/materials/{mat['id']}/file",
                files={"file": ("a.md", MD_TEXT, "text/markdown")})
    fo = db.execute(select(models.FileObject)).scalars().first()

    # то же содержимое (тот же sha256) при pending_scan → 409
    fo.scan_state = "pending_scan"
    db.commit()
    r = client.post(f"/api/v1/materials/{mat['id']}/file",
                    files={"file": ("a-copy.md", MD_TEXT, "text/markdown")})
    assert r.status_code == 409
    assert r.json()["code"] == "FILE_PENDING_SCAN"

    fo.scan_state = "infected"
    db.commit()
    r = client.post(f"/api/v1/materials/{mat['id']}/file",
                    files={"file": ("a-copy.md", MD_TEXT, "text/markdown")})
    assert r.status_code == 409
    assert r.json()["code"] == "FILE_BLOCKED"


class _SessionProxy:
    """Прокси тестовой сессии для worker-задач: close() — no-op (сессию закрывает фикстура)."""

    def __init__(self, s):
        self._s = s

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeFactory:
    def __init__(self, s):
        self._s = s

    def __call__(self):
        return _SessionProxy(self._s)


@pytest.fixture()
def worker_db(db, monkeypatch):
    """Worker-задачи (app.worker.tasks) работают с общей тестовой БД."""
    import app.worker.tasks as wt

    monkeypatch.setattr(wt, "get_session_factory", lambda: _FakeFactory(db))
    return db


def test_scan_task_sets_ready(mat, client, db, monkeypatch, worker_db):
    """§6.3: files.scan — заглушка проводит pending_scan → ready (+ system_tasks done)."""
    from app.db import models
    from app.use_cases.files import silo

    # заглушка S3
    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)

    r = client.post(f"/api/v1/materials/{mat['id']}/file",
                    files={"file": ("a.md", MD_TEXT, "text/markdown")})
    assert r.status_code == 200
    fo = db.execute(select(models.FileObject)).scalars().first()
    task = db.execute(
        select(models.SystemTask).where(models.SystemTask.task_type == "antivirus")
    ).scalars().first()
    assert task is not None

    # Вызов обработчика напрямую (синхронно, брокер не участвует)
    import app.worker.tasks as wt

    res = wt.files_scan(str(task.id), str(fo.id))
    assert res["result"] == "ready"
    db.refresh(fo)
    assert fo.scan_state == "ready"
    db.refresh(task)
    assert task.state == "done"
    assert task.attempts >= 1


def test_file_download_requires_ready(mat, client, db, monkeypatch):
    """§6.4, US-011 шаг 2: до ready отдача 409; после — стрим + аудит (FR-140)."""
    from app.db import models
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)

    client.post(f"/api/v1/materials/{mat['id']}/file",
                files={"file": ("a.md", MD_TEXT, "text/markdown")})
    fo = db.execute(select(models.FileObject)).scalars().first()

    r = client.get(f"/api/v1/materials/{mat['id']}/file")
    assert r.status_code == 409  # ещё pending_scan
    assert r.json()["code"] == "FILE_PENDING_SCAN"

    fo.scan_state = "ready"
    db.commit()

    class _FakeBody:
        def read(self):
            return MD_TEXT

        def iter_chunks(self, n):
            yield MD_TEXT

        def close(self):
            pass

    monkeypatch.setattr(silo, "get_object_stream", lambda k, r=None: (_FakeBody(), 200, {"Content-Type": "text/markdown"}))

    r = client.get(f"/api/v1/materials/{mat['id']}/file")
    assert r.status_code == 200
    assert r.content == MD_TEXT.encode("utf-8")

    # Аудит скачивания (FR-140)
    audits = db.execute(
        select(models.AuditEntry).where(models.AuditEntry.action == "file_download")
    ).scalars().all()
    assert len(audits) == 1


def test_text_md_download(mat, client, db, monkeypatch):
    """FR-107, US-014: .md доступен при наличии текста; пустой — недоступен (A2)."""
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)
    client.post(f"/api/v1/materials/{mat['id']}/file",
                files={"file": ("a.md", MD_TEXT, "text/markdown")})

    r = client.get(f"/api/v1/materials/{mat['id']}/text.md")
    assert r.status_code == 200
    assert r.content == MD_TEXT.encode("utf-8")


def test_text_md_empty_404(mat, client, db):
    """US-014 A2: «пустышка» без текста — скачивание .md недоступно."""
    r = client.get(f"/api/v1/materials/{mat['id']}/text.md")
    assert r.status_code == 404


def test_text_out_of_sync(mat, client, db, monkeypatch):
    """FR-030, 16.1-112: непустой текст + другой текстовый файл → предложение; keep → признак."""
    from app.db import models
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)
    client.post(f"/api/v1/materials/{mat['id']}/file",
                files={"file": ("a.md", MD_TEXT, "text/markdown")})
    fo = db.execute(select(models.FileObject)).scalars().first()
    fo.scan_state = "ready"
    db.commit()

    r = client.post(f"/api/v1/materials/{mat['id']}/file",
                    files={"file": ("b.md", b"#" + "Совсем другой текст\n".encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    assert r.json()["offer_text_update"] is True
    assert r.json()["text_out_of_sync"] is True

    # keep: текст сохраняется, признак остаётся
    r = client.post(f"/api/v1/materials/{mat['id']}/file?text_update_choice=keep",
                    files={"file": ("c.md", b"#" + "Ещё текст\n".encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    card = client.get(f"/api/v1/materials/{mat['id']}").json()
    assert card["text_out_of_sync"] is True
    assert card["text_content"] != "# Ещё текст\n"


def test_versions_diff_and_metadata(mat, client, db, monkeypatch):
    """US-041, FR-146: diff соседних версий — текст построчно, метаданные, file_changed."""
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)

    # версия 1 — создание (пустышка, текст ""), версия 2 — загрузка файла (file_id),
    # версия 3 — правка текста
    client.post(f"/api/v1/materials/{mat['id']}/file",
                files={"file": ("a.md", MD_TEXT, "text/markdown")})
    card = client.get(f"/api/v1/materials/{mat['id']}").json()
    r = client.patch(f"/api/v1/materials/{mat['id']}",
                     headers={"If-Match": str(card["version"])},
                     json={"text_content": "# Изменённый текст\n"})
    assert r.status_code == 200

    vs = client.get(f"/api/v1/materials/{mat['id']}/versions").json()
    latest = vs["items"][0]["number"]  # версия 3

    # diff версии 3 с 2: только текст, файл не менялся
    d = client.get(f"/api/v1/materials/{mat['id']}/versions/{latest}/diff").json()
    assert d["file_changed"] is False
    assert any("Изменённый текст" in line for line in d["text_diff"])

    # diff версии 2 с 1: файл появился — file_changed
    d2 = client.get(f"/api/v1/materials/{mat['id']}/versions/{latest - 1}/diff").json()
    assert d2["file_changed"] is True


def test_restore_version(mat, client, db, monkeypatch):
    """US-042, FR-148: восстановление — новая версия; published → draft (FR-084)."""
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)
    client.post(f"/api/v1/materials/{mat['id']}/file",
                files={"file": ("a.md", MD_TEXT, "text/markdown")})
    fo = db.execute(select(models.FileObject)).scalars().first()
    fo.scan_state = "ready"
    db.commit()

    card = client.get(f"/api/v1/materials/{mat['id']}").json()
    v_before = card["version"]
    # правка текста (версия N)
    client.patch(f"/api/v1/materials/{mat['id']}",
                 headers={"If-Match": str(v_before)},
                 json={"text_content": "# Версия 3\n"})

    # восстановление версии 1 (создание, пустой текст, без файла)
    card = client.get(f"/api/v1/materials/{mat['id']}").json()
    r = client.post(f"/api/v1/materials/{mat['id']}/versions/1/restore",
                    headers={"If-Match": str(card["version"])})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == card["version"] + 1
    card2 = client.get(f"/api/v1/materials/{mat['id']}").json()
    assert card2["text_content"] == ""  # из снапшота версии 1 (создание с text_content="")


def test_restore_in_review_keeps_status(mat, client, db, monkeypatch):
    """US-042 шаг 5/FR-085: восстановление в in_review сохраняет статус."""
    from app.db import models
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)
    client.post(f"/api/v1/materials/{mat['id']}/file",
                files={"file": ("a.md", MD_TEXT, "text/markdown")})
    fo = db.execute(select(models.FileObject)).scalars().first()
    fo.scan_state = "ready"
    db.commit()

    card = client.get(f"/api/v1/materials/{mat['id']}").json()
    rt = client.post(f"/api/v1/materials/{mat['id']}/transitions",
                     headers={"If-Match": str(card["version"])},
                     json={"to_status": "in_review"})
    assert rt.status_code == 200, rt.text
    # правка на ревью
    card = client.get(f"/api/v1/materials/{mat['id']}").json()
    client.patch(f"/api/v1/materials/{mat['id']}",
                 headers={"If-Match": str(card["version"])},
                 json={"text_content": "# На ревью\n"})

    card = client.get(f"/api/v1/materials/{mat['id']}").json()
    r = client.post(f"/api/v1/materials/{mat['id']}/versions/2/restore",
                    headers={"If-Match": str(card["version"])})
    assert r.status_code == 200
    card2 = client.get(f"/api/v1/materials/{mat['id']}").json()
    assert card2["status"] == "in_review"  # FR-085


def test_file_too_large(mat, client, db, monkeypatch):
    """FR-031/A2: файл больше 100 МБ → 413 FILE_TOO_LARGE."""
    from app.use_cases.files import silo

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)
    big = b"x" * (101 * 1024 * 1024)
    r = client.post(f"/api/v1/materials/{mat['id']}/file",
                    files={"file": ("big.bin", big, "application/octet-stream")})
    assert r.status_code == 413
    assert r.json()["code"] == "FILE_TOO_LARGE"


def test_office_convert_enqueued(mat, client, db, monkeypatch, worker_db):
    """§6.3: офисный mime после scan → задача conversion; pdf_state=converting → ready_pdf."""
    from app.db import models
    from app.use_cases.files import silo
    import app.worker.tasks as wt

    monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)

    docx = b"PK\x03\x04" + b"[Content_Types].xml" + b"word/document.xml" + b"0" * 256
    r = client.post(f"/api/v1/materials/{mat['id']}/file",
                    files={"file": ("документ.docx", docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 200
    fo = db.execute(select(models.FileObject)).scalars().first()
    assert fo.mime_type.startswith("application/vnd.openxmlformats")

    task = db.execute(
        select(models.SystemTask).where(models.SystemTask.task_type == "antivirus")
    ).scalars().first()
    # Подменяем постановку convert-задачи (брокера нет)
    monkeypatch.setattr(wt, "files_convert", _fake_convert_task(wt))

    res = wt.files_scan(str(task.id), str(fo.id))
    assert res["result"] == "ready"
    db.refresh(fo)
    # conversion-задача создана (office mime)
    conv = db.execute(
        select(models.SystemTask).where(models.SystemTask.task_type == "conversion")
    ).scalars().all()
    assert len(conv) == 1


class _FakeBody:
    pass


def _fake_convert_task(wt):
    class _T:
        @staticmethod
        def apply_async(*a, **k):
            return None

    return _T()
