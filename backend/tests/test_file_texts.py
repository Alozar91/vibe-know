# Тесты пост-MVP шага [8]: извлечение текста файлов (16.1-121, FR-154).
# Конвейер (worker/Celery/silo/MarkItDown) — заглушки/monkeypatch;
# file_texts-модель, mime-предикат, FTS-вклад (SQL), RAG-объединённый текст,
# ILIKE-источник и reconcile-бэкфилл проверяются напрямую.
import uuid

import pytest
from sqlalchemy import select

from app.db import models


# --- Хелперы (по образцу test_rag_indexing) ------------------------------

class _FakeBody:
    """S3 body-заглушка: read()/close() как у botocore StreamingBody."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        pass


def _make_group(db, name="Группа FileRAG"):
    g = models.Group(name=name, normalized_name=name.lower(), path="pending")
    db.add(g)
    db.flush()
    g.path = f"{g.id}/"
    db.commit()
    return g


def _make_material(db, group, name="Материал с файлом", text=""):
    m = models.Material(
        group_id=group.id, name=name, normalized_name=name.lower(),
        type_id=_type_id(db), status=models.MaterialStatus("published"),
        author_id=_user_id(db), last_editor_id=_user_id(db),
        text_content=text,
    )
    db.add(m)
    db.flush()
    # Строка контентной версии (§5.1): без неё RAG index_material → missing
    from app.use_cases.materials.versions import commit_version, snapshot_from_material

    commit_version(db, m, type("U", (), {"user_id": _user_id(db)})(),
                   snapshot=snapshot_from_material(db, m))
    db.commit()
    return m


_type_cache = {}


def _type_id(db):
    if "id" not in _type_cache:
        t = models.MaterialType(name=f"Тип FR {uuid.uuid4().hex[:8]}")
        db.add(t)
        db.flush()
        _type_cache["id"] = t.id
        db.commit()
    return _type_cache["id"]


_user_cache = {}


def _user_id(db):
    if "id" not in _user_cache:
        u = models.User(keycloak_id=f"kc-fr-{uuid.uuid4().hex[:8]}",
                        display_name="FR Пользователь")
        db.add(u)
        db.flush()
        _user_cache["id"] = u.id
        db.commit()
    return _user_cache["id"]


def _make_file(db, m, sha_hex=None, mime="application/pdf", ready=True):
    """Файл, привязанный к материалу (ref_count=1, current_file_id)."""
    sha = sha_hex or uuid.uuid4().hex
    fo = models.FileObject(
        cas_key=sha, filename=f"{sha[:8]}.pdf", mime_type=mime,
        size_bytes=1024, sha256=sha, scan_state="ready", ref_count=1,
    )
    db.add(fo)
    db.flush()
    m.current_file_id = fo.id
    db.commit()
    return fo


# --- mime-предикат --------------------------------------------------------

def test_is_extractable_mime():
    """FR-154: DOCX/XLSX/PPTX/PDF — извлекаются; старые MS-форматы, графика, сканы — нет."""
    from app.use_cases.files.mime_detect import is_extractable_mime

    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    pptx = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    assert is_extractable_mime(docx)
    assert is_extractable_mime(xlsx)
    assert is_extractable_mime(pptx)
    assert is_extractable_mime("application/pdf")
    # Старые MS-форматы: конвертация (§6.3), но без извлечения — нет текстового слоя
    assert not is_extractable_mime("application/msword")
    assert not is_extractable_mime("application/vnd.ms-excel")
    assert not is_extractable_mime("image/png")
    assert not is_extractable_mime("text/plain")


# --- Модель file_texts + задача files.extract -----------------------------

class TestFilesExtract:
    def test_extract_ready(self, db, monkeypatch):
        """§6.3: успешное извлечение → file_texts ready + text; FTS-хук отработал."""
        import app.worker.tasks as wt
        from app.use_cases.files import silo

        g = _make_group(db)
        m = _make_material(db, g, text="Авторское описание")
        fo = _make_file(db, m)

        # Заглушки: MarkItDown и silo
        monkeypatch.setattr(silo, "get_object_stream",
                            lambda key, range_header=None: (_FakeBody(b"data"), 200, {}))
        monkeypatch.setattr(silo, "put_object", lambda *a, **k: None)

        class _R:
            text_content = "# Извлечённый текст\nсодержимое документа"

        class _MD:
            def convert(self, path):
                return _R()

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "markitdown":
                import types
                mod = types.ModuleType("markitdown")
                mod.MarkItDown = _MD
                return mod
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        # Сессия worker'а → общая тестовая БД
        from tests.test_files_versions import _FakeFactory

        monkeypatch.setattr(wt, "get_session_factory", lambda: _FakeFactory(db))

        task = models.SystemTask(task_type="extraction", object_type="file",
                                 object_id=fo.id, state="queued")
        db.add(task)
        db.commit()

        res = wt.files_extract(str(task.id), str(fo.id))
        assert res["result"] == "ready", res

        ft = db.get(models.FileText, fo.id)
        assert ft is not None
        assert ft.state == "ready"
        assert "Извлечённый текст" in ft.text
        assert ft.extractor.startswith("markitdown")

    def test_extract_failure_marks_failed(self, db, monkeypatch):
        """Отказ (повреждённый документ) → после исчерпания ретраев file_texts
        failed, материал не блокируется (как FR-060)."""
        import app.worker.tasks as wt
        from app.use_cases.files import silo

        g = _make_group(db)
        m = _make_material(db, g)
        fo = _make_file(db, m)

        monkeypatch.setattr(silo, "get_object_stream",
                            lambda key, range_header=None: (_FakeBody(b"data"), 200, {}))

        class _MD:
            def convert(self, path):
                raise ValueError("повреждённый документ")

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "markitdown":
                import types
                mod = types.ModuleType("markitdown")
                mod.MarkItDown = _MD
                return mod
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        from tests.test_files_versions import _FakeFactory

        monkeypatch.setattr(wt, "get_session_factory", lambda: _FakeFactory(db))

        task = models.SystemTask(task_type="extraction", object_type="file",
                                 object_id=fo.id, state="queued")
        db.add(task)
        db.commit()

        # Ретраи выключены (эмуляция исчерпания): сразу ветка failed
        monkeypatch.setattr(wt, "EXTRACT_MAX_RETRIES", 0)
        res = wt.files_extract(str(task.id), str(fo.id))
        assert res["result"] == "failed"
        assert "повреждённый документ" in res["error"]

        ft = db.get(models.FileText, fo.id)
        assert ft is not None
        assert ft.state == "failed"
        assert "повреждённый" in (ft.error or "")

    def test_extract_empty_result_is_failed(self, db, monkeypatch):
        """Документ без текстового слоя (скан): пустой результат → failed."""
        import app.worker.tasks as wt
        from app.use_cases.files import silo

        g = _make_group(db)
        m = _make_material(db, g)
        fo = _make_file(db, m)

        monkeypatch.setattr(silo, "get_object_stream",
                            lambda key, range_header=None: (_FakeBody(b"data"), 200, {}))

        class _R:
            text_content = "   "

        class _MD:
            def convert(self, path):
                return _R()

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "markitdown":
                import types
                mod = types.ModuleType("markitdown")
                mod.MarkItDown = _MD
                return mod
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        from tests.test_files_versions import _FakeFactory

        monkeypatch.setattr(wt, "get_session_factory", lambda: _FakeFactory(db))

        task = models.SystemTask(task_type="extraction", object_type="file",
                                 object_id=fo.id, state="queued")
        db.add(task)
        db.commit()

        # Ретраи выключены (эмуляция исчерпания): сразу ветка failed
        monkeypatch.setattr(wt, "EXTRACT_MAX_RETRIES", 0)
        res = wt.files_extract(str(task.id), str(fo.id))
        assert res["result"] == "failed"
        ft = db.get(models.FileText, fo.id)
        assert ft.state == "failed"

    def test_maybe_extract_skips_cached(self, db, monkeypatch):
        """Кэш по sha256: готовое извлечение → повторная постановка не требуется."""
        import app.worker.tasks as wt
        from tests.test_files_versions import _FakeFactory

        g = _make_group(db)
        m = _make_material(db, g)
        fo = _make_file(db, m)
        db.add(models.FileText(file_id=fo.id, state="ready", text="уже готово"))
        db.commit()

        created = []

        class _T:
            @staticmethod
            def apply_async(*a, **k):
                created.append(a)

        monkeypatch.setattr(wt, "files_extract", _T())
        monkeypatch.setattr(wt, "get_session_factory", lambda: _FakeFactory(db))

        wt._maybe_extract(fo)
        assert created == []  # кэш валиден

    def test_maybe_extract_enqueues(self, db, monkeypatch):
        """Готового извлечения нет → extraction-задача создана (queued)."""
        import app.worker.tasks as wt
        from tests.test_files_versions import _FakeFactory

        g = _make_group(db)
        m = _make_material(db, g)
        fo = _make_file(db, m, mime="application/pdf")

        created = []

        class _T:
            @staticmethod
            def apply_async(*a, **k):
                created.append(a)

        monkeypatch.setattr(wt, "files_extract", _T())
        monkeypatch.setattr(wt, "get_session_factory", lambda: _FakeFactory(db))

        wt._maybe_extract(fo)
        assert len(created) == 1
        task = db.execute(
            select(models.SystemTask).where(models.SystemTask.task_type == "extraction")
        ).scalars().first()
        assert task is not None and task.state == "queued"


# --- Вес D: SQL-выражение FTS --------------------------------------------

class TestTsvWeightD:
    def test_tsv_expr_contains_file_texts(self):
        """§7.1: build_tsv_sql_expr содержит подзапрос file_texts с весом D."""
        from app.use_cases.materials.search_common import build_tsv_sql_expr

        sql = str(build_tsv_sql_expr("russian").text)
        assert "setweight(to_tsvector('russian'," in sql
        # Вес D — извлечённый текст из file_texts по текущему файлу
        assert "'D')" in sql
        assert "file_texts" in sql
        assert "current_file_id" in sql
        assert "ft.state = 'ready'" in sql

    def test_tsv_expr_all_weights(self):
        """Веса A/B/C сохраняются (регресс: старые источники не потеряны)."""
        from app.use_cases.materials.search_common import build_tsv_sql_expr

        sql = str(build_tsv_sql_expr("russian").text)
        assert "'A')" in sql  # название
        assert "'B')" in sql  # атрибуты + теги
        assert "'C')" in sql  # текстовое представление
        assert "text_content" in sql


# --- RAG: объединённый текст чанкования ----------------------------------

class TestVersionText:
    def test_version_text_combined(self, db, rag_on):
        """16.1-121: текст чанкования = описание + извлечённый текст файла."""
        from app.rag.indexing import _version_text

        g = _make_group(db)
        m = _make_material(db, g, text="Описание материала")
        fo = _make_file(db, m)
        db.add(models.FileText(file_id=fo.id, state="ready", text="Текст из файла"))
        db.commit()

        ver = db.execute(
            select(models.MaterialVersion).where(
                models.MaterialVersion.material_id == m.id)
        ).scalars().first()
        if ver is None:
            from app.use_cases.materials.versions import commit_version, snapshot_from_material

            ver = commit_version(db, m, type("U", (), {"user_id": _user_id(db)})(),
                                 snapshot=snapshot_from_material(db, m))

        text = _version_text(db, ver)
        assert "Описание материала" in text  # авторское описание — первым
        assert "Текст из файла" in text      # извлечённый текст — вторым
        assert text.index("Описание материала") < text.index("Текст из файла")

    def test_version_text_without_file_text(self, db, rag_on):
        """Извлечение не готово/не удалось — только описание (§6.3)."""
        from app.rag.indexing import _version_text

        g = _make_group(db)
        m = _make_material(db, g, text="Только описание")
        fo = _make_file(db, m)
        db.add(models.FileText(file_id=fo.id, state="failed", text=None,
                               error="повреждён"))
        db.commit()

        from app.use_cases.materials.versions import commit_version, snapshot_from_material

        commit_version(db, m, type("U", (), {"user_id": _user_id(db)})(),
                       snapshot=snapshot_from_material(db, m))
        ver = db.execute(
            select(models.MaterialVersion).where(
                models.MaterialVersion.material_id == m.id)
        ).scalars().first()
        text = _version_text(db, ver)
        assert text == "Только описание"

    def test_version_text_file_only(self, db, rag_on):
        """Материал без описания (docx): текст чанкования — извлечённый текст."""
        from app.rag.indexing import _version_text

        g = _make_group(db)
        m = _make_material(db, g, text="")
        fo = _make_file(db, m)
        db.add(models.FileText(file_id=fo.id, state="ready", text="Содержимое docx"))
        db.commit()

        from app.use_cases.materials.versions import commit_version, snapshot_from_material

        commit_version(db, m, type("U", (), {"user_id": _user_id(db)})(),
                       snapshot=snapshot_from_material(db, m))
        ver = db.execute(
            select(models.MaterialVersion).where(
                models.MaterialVersion.material_id == m.id)
        ).scalars().first()
        text = _version_text(db, ver)
        assert text == "Содержимое docx"


# --- RAG: индексация по объединённому тексту (сквозная) ------------------

class FakeClient:
    """Детерминированный вектор (упрощённая копия из test_rag_indexing)."""

    def __init__(self, model="fake-embed-v1", dim=3):
        self.base_url = "http://fake"
        self.api_key = "k"
        self.model = model
        self.dim = dim
        self.batch = 32
        self.calls = 0
        self.embedded_texts: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def embed(self, texts):
        self.calls += 1
        self.embedded_texts.extend(texts)
        return [[len(t) % 10 / 10.0, sum(map(ord, t[:100])) % 7 / 7.0, 1.0]
                for t in texts]

    def probe(self):
        return {"ok": True, "model": self.model, "dim": self.dim}


@pytest.fixture()
def rag_on(db, monkeypatch):
    import app.rag.indexing as idx

    monkeypatch.setattr(idx, "_settings", lambda: type("S", (), {
        "rag_embedding_base_url": "http://fake",
        "rag_embedding_api_key": "k",
        "rag_embedding_model": "fake-embed-v1",
        "rag_embedding_dim": 3,
        "rag_embedding_batch": 32,
        "rag_embedding_timeout": 5.0,
    })())
    return db


class TestRagIndexWithFileText:
    def test_index_material_includes_file_text(self, db, rag_on):
        """Чанки строятся по объединённому тексту: фраза из файла попадает в чанки."""
        from app.rag.indexing import index_material

        g = _make_group(db)
        m = _make_material(db, g, text="Короткое описание.")
        fo = _make_file(db, m)
        db.add(models.FileText(file_id=fo.id, state="ready",
                               text="Уникальная фраза из документа. " * 30))
        db.commit()

        res = index_material(db, m.id, client=FakeClient())
        assert res["result"] == "indexed", res

        chunks = db.execute(
            select(models.RagChunk).where(models.RagChunk.material_id == m.id)
        ).scalars().all()
        joined = " ".join(c.content for c in chunks)
        assert "Уникальная фраза" in joined

    def test_reindex_after_extract(self, db, rag_on, monkeypatch):
        """Файл проиндексирован без извлечения; извлечение готово → _after_extract
        пересчитывает FTS-хук и ставит RAG-pending (§7.1/§7.7)."""
        import app.worker.tasks as wt

        g = _make_group(db)
        m = _make_material(db, g, text="Описание без файла.")
        fo = _make_file(db, m)

        # Материал уже проиндексирован (по одному описанию)
        res = _run_index(db, m)
        assert res["result"] == "indexed"
        db.expire_all()

        # Извлечение готово после индексации
        db.add(models.FileText(file_id=fo.id, state="ready",
                               text="Текст, которого не было при индексации."))
        db.commit()

        enqueued = []
        from tests.test_files_versions import _FakeFactory

        monkeypatch.setattr(wt, "get_session_factory", lambda: _FakeFactory(db))
        # SQLite-защита hook_after_change: подменяем хук целиком (регистрация
        # refs на сессии — как PG-ветка; flush ниже читает эти refs)
        import app.rag.indexing as idx

        def _hook(db, material):
            idx.mark_pending(db, material)
            refs = getattr(db, "_pending_rag_refs", None)
            if refs is None:
                refs = []
                db._pending_rag_refs = refs
            refs.append(str(material.id))

        monkeypatch.setattr(idx, "hook_after_change", _hook)
        # flush_rag_enqueue импортирует rag_index_material локально — подменяем
        # через sys.modules
        import sys
        import types as _types

        fake_mod = _types.SimpleNamespace(
            rag_index_material=type("T", (), {
                "apply_async": staticmethod(lambda *a, **k: enqueued.append(a)),
            })(),
        )
        real_mod = sys.modules.get("app.worker.tasks")
        sys.modules["app.worker.tasks"] = fake_mod
        try:
            wt._after_extract(fo)
        finally:
            if real_mod is not None:
                sys.modules["app.worker.tasks"] = real_mod
        db.expire_all()
        db.refresh(m)
        assert m.rag_state == "pending"  # RAG-хук поставлен
        assert enqueued  # постановка в брокер была


def _run_index(db, m):
    from app.rag.indexing import index_material

    return index_material(db, m.id, client=FakeClient())


# --- Поиск по извлечённому тексту (SQLite API-ветка partial) -------------

class TestSearchFileText:
    def test_partial_finds_file_text(self, db, monkeypatch):
        """FR-154/US-034 A1: материал без описания находится по содержимому файла
        (частичное совпадение — ILIKE по file_texts через EXISTS)."""
        from tests.test_file_texts_api import _setup_client

        client, g, t, m = _setup_client(db)
        m_orm = db.get(models.Material, uuid.UUID(m["id"]))

        fo = _make_file(db, m_orm, mime="application/pdf")
        db.add(models.FileText(file_id=fo.id, state="ready",
                               text="Уникальный термин парацетамоловый внутри документа"))
        db.commit()

        # partial=false: по содержимому файла не ищем (только FTS на PG)
        r = client.get("/api/v1/search?q=парацетамоловый")
        assert r.status_code == 200
        assert r.json()["items"] == []

        # partial=true: ILIKE по file_texts находит
        r = client.get("/api/v1/search?q=парацетамоловый&partial=true")
        assert r.status_code == 200
        names = [i["name"] for i in r.json()["items"]]
        assert "Материал с файлом" in names

    def test_failed_extraction_not_searchable(self, db, monkeypatch):
        """A6/FR-154: извлечение не удалось → материал по содержимому не находится."""
        from tests.test_file_texts_api import _setup_client

        client, g, t, m = _setup_client(db)
        m_orm = db.get(models.Material, uuid.UUID(m["id"]))

        fo = _make_file(db, m_orm, mime="application/pdf")
        db.add(models.FileText(file_id=fo.id, state="failed", text=None,
                               error="повреждён"))
        db.commit()

        r = client.get("/api/v1/search?q=парацетамоловый&partial=true")
        assert r.status_code == 200
        assert r.json()["items"] == []


class TestReconcile:
    def test_reconcile_includes_extraction(self, db, monkeypatch):
        """files.reconcile перезапускает и extraction-задачи (LLD §9)."""
        import app.worker.tasks as wt

        from tests.test_files_versions import _FakeFactory

        monkeypatch.setattr(wt, "get_session_factory", lambda: _FakeFactory(db))

        fo = models.FileObject(
            cas_key=uuid.uuid4().hex, filename="a.pdf", mime_type="application/pdf",
            size_bytes=1, sha256=uuid.uuid4().hex, scan_state="ready", ref_count=1,
        )
        db.add(fo)
        t = models.SystemTask(task_type="extraction", object_type=fo.id,
                              object_id=fo.id, state="queued")
        db.add(t)
        db.commit()

        scanned, converted, extracted = [], [], []

        class _T:
            def __init__(self, sink):
                self._sink = sink

            @staticmethod
            def _mk(sink):
                class _C:
                    @staticmethod
                    def apply_async(*a, **k):
                        sink.append(a)
                return _C()

        monkeypatch.setattr(wt, "files_scan", _T._mk(scanned))
        monkeypatch.setattr(wt, "files_convert", _T._mk(converted))
        monkeypatch.setattr(wt, "files_extract", _T._mk(extracted))

        res = wt.files_reconcile.run()
        assert res["restarted"] >= 1
        assert len(extracted) == 1
