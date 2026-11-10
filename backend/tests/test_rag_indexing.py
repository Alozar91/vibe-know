# Тесты RAG-конвейера индексации (пост-MVP шаг [7] ч.2, RAG_DESIGN §5, §6).
# Embedding-провайдер — фиктивный (детерминированный вектор из текста);
# worker-задачи вызываются напрямую (без брокера) — как test_files_versions.
import uuid

import pytest
from sqlalchemy import select

from app.db import models


# --- Фиктивный провайдер эмбеддингов -----------------------------

class FakeClient:
    """Детерминированный «вектор»: [len(text) % 10 / 10, hash % 7 / 7, 1.0]."""

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
        return [self._vec(t) for t in texts]

    def _vec(self, t):
        return [len(t) % 10 / 10.0, sum(map(ord, t[:100])) % 7 / 7.0, 1.0]

    def probe(self):
        return {"ok": True, "model": self.model, "dim": self.dim}


@pytest.fixture()
def rag_on(db, monkeypatch):
    """Конвейер включён (base_url задан) даже на SQLite-тестах."""
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


def _make_group(db, name="Группа RAG2", parent_id=None):
    parent_path = ""
    if parent_id:
        parent_path = db.get(models.Group, parent_id).path
    g = models.Group(name=name, normalized_name=name.lower(), parent_id=parent_id,
                     path="pending")
    db.add(g)
    db.flush()
    g.path = f"{parent_path}{g.id}/"
    db.commit()
    return g


def _make_material(db, group, text="Текст материала для индексации.", status="published"):
    m = models.Material(
        group_id=group.id, name="Материал RAG", normalized_name="материал rag",
        type_id=_type_id(db), status=models.MaterialStatus(status),
        author_id=_user_id(db), last_editor_id=_user_id(db),
        text_content=text,
    )
    db.add(m)
    db.flush()
    from app.use_cases.materials.versions import snapshot_from_material, commit_version

    commit_version(db, m, type("U", (), {"user_id": _user_id(db)})(),
                   snapshot=snapshot_from_material(db, m))
    db.commit()
    return m


_type_cache = {}


def _type_id(db):
    if "id" not in _type_cache:
        t = models.MaterialType(name=f"Тип RAG {uuid.uuid4().hex[:8]}")
        db.add(t)
        db.flush()
        _type_cache["id"] = t.id
        db.commit()
    return _type_cache["id"]


_user_cache = {}


def _user_id(db):
    if "id" not in _user_cache:
        u = models.User(keycloak_id=f"kc-rag-{uuid.uuid4().hex[:8]}",
                        display_name="RAG Пользователь")
        db.add(u)
        db.flush()
        _user_cache["id"] = u.id
        db.commit()
    return _user_cache["id"]


class TestIndexMaterial:
    def test_skipped_on_sqlite_by_default(self, db):
        """Без включения конвейера (SQLite-защита): skipped, ничего не падает."""
        from app.rag.indexing import index_material

        g = _make_group(db)
        m = _make_material(db, g)
        res = index_material(db, m.id)
        assert res["result"] == "skipped"

    def test_full_pipeline(self, db, rag_on, monkeypatch):
        """§8-2 приёмка: индексация → чанки с векторами, state=indexed."""
        from app.rag.indexing import index_material
        from app.rag.chunkers import content_hash

        g = _make_group(db)
        # Явный markdown-чанкер (heading_path в meta проверяем тут)
        db.add(models.RagGroupConfig(group_id=g.id, chunker="markdown",
                                     params={"max_len": 500},
                                     updated_by=_user_id(db)))
        db.commit()
        text = "# Раздел\n\n" + "\n\n".join(f"Абзац {i}. " + "т" * 120 for i in range(80))
        m = _make_material(db, g, text=text)
        client = FakeClient()

        res = index_material(db, m.id, client=client)
        assert res["result"] == "indexed" and res["chunks"] > 0
        db.refresh(m)
        assert m.rag_state == "indexed" and m.rag_stale is False

        chunks = db.execute(
            select(models.RagChunk).where(models.RagChunk.material_id == m.id)
            .order_by(models.RagChunk.ord)
        ).scalars().all()
        assert len(chunks) == res["chunks"]
        assert all(c.embedding is not None for c in chunks)
        assert all(c.embedding_model == "fake-embed-v1" for c in chunks)
        assert all(c.content_hash == content_hash(c.content) for c in chunks)
        # Чанки привязаны к версии и группе
        assert all(c.version_id is not None for c in chunks)
        assert all(c.group_id == g.id for c in chunks)
        # markdown-чанкер: heading_path в meta
        assert any(c.meta.get("heading_path") == ["Раздел"] for c in chunks)
        # эмбеддинг вызывался (пачки)
        assert client.calls >= 1

    def test_reindex_replaces_chunks(self, db, rag_on):
        """Повторная индексация: прежние чанки версии удалены (§2, §5-5)."""
        from app.rag.indexing import index_material

        g = _make_group(db)
        m = _make_material(db, g, text="Версия один. " * 30)
        client = FakeClient()
        index_material(db, m.id, client=client)
        first = db.execute(
            select(models.RagChunk).where(models.RagChunk.material_id == m.id)
        ).scalars().all()
        ids1 = {c.id for c in first}

        # Новый текст → другая версия → другие чанки
        m.text_content = "Совершенно новый текст версии два. " * 30
        m.version += 1
        from app.use_cases.materials.versions import snapshot_from_material, commit_version

        commit_version(db, m, type("U", (), {"user_id": _user_id(db)})(),
                       snapshot=snapshot_from_material(db, m))
        res = index_material(db, m.id, client=client)
        assert res["result"] == "indexed"
        chunks = db.execute(
            select(models.RagChunk).where(models.RagChunk.material_id == m.id)
        ).scalars().all()
        # Все чанки — новой версии; чанки версии 1 удалены
        ver2 = db.execute(
            select(models.MaterialVersion.id).where(
                models.MaterialVersion.material_id == m.id,
                models.MaterialVersion.number == m.version)
        ).scalar_one()
        assert all(c.version_id == ver2 for c in chunks)
        assert not ({c.id for c in chunks} & ids1)

    def test_unchanged_fastpath(self, db, rag_on):
        """§5 экономия: тот же текст → content_hash совпал → эмбеддинг не звался."""
        from app.rag.indexing import index_material

        g = _make_group(db)
        m = _make_material(db, g, text="Стабильный текст. " * 50)
        client = FakeClient()
        index_material(db, m.id, client=client)
        calls_after_first = client.calls

        m.rag_state = "pending"  # хук поставил
        m.rag_stale = True
        db.commit()
        res = index_material(db, m.id, client=client)
        assert res["result"] == "unchanged"
        assert client.calls == calls_after_first  # эмбеддинг не вызывался
        db.refresh(m)
        assert m.rag_state == "indexed" and m.rag_stale is False

    def test_disabled_group_clears_chunks(self, db, rag_on):
        """enabled=false на группе: чанки удалены, state=none."""
        from app.rag.indexing import index_material

        g = _make_group(db)
        m = _make_material(db, g, text="Текст. " * 40)
        client = FakeClient()
        index_material(db, m.id, client=client)
        assert m.rag_state == "indexed"

        db.add(models.RagGroupConfig(group_id=g.id, chunker="whole",
                                     params={}, enabled=False,
                                     updated_by=_user_id(db)))
        db.commit()
        res = index_material(db, m.id, client=client)
        assert res["result"] == "disabled"
        db.refresh(m)
        assert m.rag_state == "none"
        assert db.execute(
            select(models.RagChunk).where(models.RagChunk.material_id == m.id)
        ).scalars().all() == []

    def test_system_default_used(self, db, rag_on):
        """Нет явных настроек → системный дефолт (rag.default_chunker, §3.1)."""
        from app.rag.indexing import index_material, resolve_effective

        g = _make_group(db)
        m = _make_material(db, g, text="Текст. " * 20)
        eff = resolve_effective(db, m)
        assert eff is not None
        assert eff["chunker"] == "recursive"  # сид 0011 (или дефолт функции)
        res = index_material(db, m.id, client=FakeClient())
        assert res["result"] == "indexed"

    def test_no_text_indexed_empty(self, db, rag_on):
        """Пустышка без текста: indexed с 0 чанков (не ошибка)."""
        from app.rag.indexing import index_material

        g = _make_group(db)
        m = _make_material(db, g, text=None)
        res = index_material(db, m.id, client=FakeClient())
        assert res["result"] == "indexed" and res["chunks"] == 0
        db.refresh(m)
        assert m.rag_state == "indexed"


class TestEmbeddingClient:
    def test_disabled_without_base_url(self):
        from app.rag.embeddings import EmbeddingClient

        c = EmbeddingClient(type("S", (), {
            "rag_embedding_base_url": "", "rag_embedding_api_key": "",
            "rag_embedding_model": "m", "rag_embedding_dim": 1536,
            "rag_embedding_batch": 32, "rag_embedding_timeout": 5.0,
        })())
        assert c.enabled is False

    def test_dim_mismatch_rejected(self, monkeypatch):
        """Провайдер вернул не ту размерность → EmbeddingError (миграция нужна)."""
        from app.rag import embeddings as em

        class _Resp:
            status_code = 200
            text = ""
            def json(self):
                return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

        class _Client:
            def __init__(self, *a, **k):
                pass
            def post(self, *a, **k):
                return _Resp()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        monkeypatch.setattr(em.httpx, "Client", _Client)
        c = em.EmbeddingClient(type("S", (), {
            "rag_embedding_base_url": "http://x", "rag_embedding_api_key": "",
            "rag_embedding_model": "m", "rag_embedding_dim": 1536,
            "rag_embedding_batch": 32, "rag_embedding_timeout": 5.0,
        })())
        with pytest.raises(em.EmbeddingError, match="размерность"):
            c.embed(["текст"])

    def test_batches(self, monkeypatch):
        """Пачки: 100 текстов при batch=32 → 4 запроса, порядок сохранён."""
        from app.rag import embeddings as em

        seen_sizes = []

        class _Resp:
            status_code = 200
            text = ""
            def __init__(self, n):
                self.n = n
            def json(self):
                return {"data": [{"index": i, "embedding": [float(i), 1.0]}
                                 for i in range(self.n)]}

        class _Client:
            def __init__(self, *a, **k):
                pass
            def post(self, url, json=None, headers=None):
                seen_sizes.append(len(json["input"]))
                return _Resp(len(json["input"]))
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        monkeypatch.setattr(em.httpx, "Client", _Client)
        c = em.EmbeddingClient(type("S", (), {
            "rag_embedding_base_url": "http://x", "rag_embedding_api_key": "",
            "rag_embedding_model": "m", "rag_embedding_dim": 2,
            "rag_embedding_batch": 32, "rag_embedding_timeout": 5.0,
        })())
        vecs = c.embed([f"t{i}" for i in range(100)])
        assert seen_sizes == [32, 32, 32, 4]
        assert len(vecs) == 100
        # Каждая пачка нумерует индексы с 0; порядок в пачке = порядок входа
        assert vecs[0] == [0.0, 1.0]
        assert vecs[31] == [31.0, 1.0]
        assert vecs[32] == [0.0, 1.0]  # начало второй пачки


class TestWorkerTasks:
    def test_index_material_task(self, db, rag_on, worker_db):
        """Задача rag.index_material напрямую: indexed на SQLite-«пропуске»."""
        import app.worker.tasks as wt
        from app.rag.indexing import index_material as _idx

        g = _make_group(db)
        m = _make_material(db, g, text="Текст. " * 10)
        # На SQLite задача вернёт skipped — но не упадёт
        res = wt.rag_index_material(str(m.id))
        assert res["result"] in ("skipped", "indexed")

    def test_reindex_subtree_missing_group(self, db, worker_db):
        import app.worker.tasks as wt

        res = wt.rag_reindex_group_subtree(str(uuid.uuid4()))
        assert res == {"result": "missing"}

    def test_reconcile_sqlite_skip(self, db, worker_db):
        import app.worker.tasks as wt

        res = wt.rag_reconcile()
        assert res == {"reindexed": 0, "skipped": "sqlite"}


@pytest.fixture()
def worker_db(db, monkeypatch):
    """Worker-задачи работают с общей тестовой БД (как test_files_versions)."""
    import app.worker.tasks as wt

    class _Proxy:
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

    class _Factory:
        def __init__(self, s):
            self._s = s
        def __call__(self):
            return _Proxy(self._s)

    monkeypatch.setattr(wt, "get_session_factory", lambda: _Factory(db))
    return db
