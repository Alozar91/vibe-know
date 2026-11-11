# Тесты RAG-retrieval (пост-MVP шаг [7] ч.3, RAG_DESIGN §7).
# Векторная логика — через FakeClient (indexing) и подмену _query_vector;
# права — предикат §3.2 (deny/SA/авторство черновиков); фильтр группы §7.2.
import uuid

import pytest
from sqlalchemy import select

from app.db import models


def _make_group(db, name="Группа поиска", parent_id=None):
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


def _user(db, name):
    u = models.User(keycloak_id=f"kc-{name}-{uuid.uuid4().hex[:6]}", display_name=name)
    db.add(u)
    db.commit()
    return u


def _material(db, group, author, name, text, status="published"):
    m = models.Material(
        group_id=group.id, name=name, normalized_name=name.lower(),
        type_id=_type_id(db), status=models.MaterialStatus(status),
        author_id=author.id, last_editor_id=author.id, text_content=text,
    )
    db.add(m)
    db.flush()
    from app.use_cases.materials.versions import snapshot_from_material, commit_version

    commit_version(db, m, type("U", (), {"user_id": author.id})(),
                   snapshot=snapshot_from_material(db, m))
    db.commit()
    return m


_type_cache = {}


def _type_id(db):
    if "id" not in _type_cache:
        t = models.MaterialType(name=f"Тип поиска {uuid.uuid4().hex[:8]}")
        db.add(t)
        db.flush()
        _type_cache["id"] = t.id
        db.commit()
    return _type_cache["id"]


def _index(db, m, client=None):
    """Прямая индексация с FakeClient (SQLite — векторная логика с клиентом)."""
    from app.rag.indexing import index_material

    if client is None:
        client = _FakeClient()
    return index_material(db, m.id, client=client)


class _FakeClient:
    """«Вектор» — хеш слова запроса: одинаковые слова → близкие векторы."""

    base_url = "http://fake"
    api_key = "k"
    model = "fake-v1"
    dim = 8
    batch = 32
    enabled = True

    def embed(self, texts):
        return [self._vec(t) for t in texts]

    def _vec(self, t):
        # 8-мерный псевдовектор: нормированные частоты символьных биграмм
        v = [0.0] * 8
        for ch in (t or "").lower()[:200]:
            v[ord(ch) % 8] += 1.0
        n = sum(v) or 1.0
        return [x / n for x in v]

    def probe(self):
        return {"ok": True, "model": self.model, "dim": self.dim}


@pytest.fixture()
def rag_query_on(monkeypatch):
    """Вектор запроса — тем же FakeClient (без HTTP)."""
    from app.use_cases.rag import retrieve as ret

    monkeypatch.setattr(ret, "_query_vector", lambda db, q: _FakeClient()._vec(q) and
                        "[" + ",".join(repr(float(x)) for x in _FakeClient()._vec(q)) + "]")


@pytest.fixture()
def users(db):
    class U:
        def __init__(self):
            self.author = _user(db, "Автор Материалов")
            self.reader = _user(db, "Читатель Сторонний")
            self.sa = None  # СА — через as_user/флаг
    return U(db)


def _principal(db, user, is_super=False):
    from app.api.deps import CurrentUser

    token_info = {"sub": user.keycloak_id, "active": True}
    return CurrentUser(user, token_info, is_super)


class TestRetrieveChunks:
    def test_vector_search_returns_chunks(self, db, rag_query_on):
        """§7.1-2: чанки с score и material-ссылками; структура полная."""
        from app.use_cases.rag.retrieve import retrieve_chunks

        u = _user(db, "Пользователь Вектор")
        principal = _principal(db, u, is_super=True)  # СА — без прав-настройки
        g = _make_group(db)
        m1 = _material(db, g, u, "Регламент паркетных работ",
                       "Паркет шлифуется лаком в три слоя.\n\n" + "Наполнение. " * 50)
        m2 = _material(db, g, u, "Инструкция по кофе",
                       "Кофе варится эспрессо-машиной.\n\n" + "Наполнение. " * 50)
        _index(db, m1)
        _index(db, m2)

        out = retrieve_chunks(db, principal, q="паркет", k=5)
        assert out["mode"] == "vector" and out["total"] >= 1
        top = out["items"][0]
        assert top["score"] is not None and top["content"]
        assert top["material"]["name"]
        assert "deep_link" not in top  # deep_link добавляет транспорт
        # Оба материала видны (SQLite-заглушка дистанции не даёт векторной
        # семантики — порядок релевантности проверяется на живом стеке)
        mids = {it["material"]["id"] for it in out["items"]}
        assert str(m1.id) in mids and str(m2.id) in mids

    def test_rights_filter_deny(self, db, rag_query_on):
        """§7.3: deny на группу скрывает материал даже в векторной выдаче."""
        from app.use_cases.rag.retrieve import retrieve_chunks

        author = _user(db, "Автор Денаида")
        reader = _user(db, "Читатель Денаида")
        g = _make_group(db)
        m = _material(db, g, author, "Секретный регламент",
                      "Секретное содержимое паркетчика. " * 40)
        _index(db, m)

        # deny view на группу для reader (PermissionEntry.state='deny')
        snap = models.PermissionSnapshot(
            object_type="group", object_id=g.id, role_id=None, created_by=author.id)
        # role_id None — виртуальная «Все пользователи»… нужен персональный deny:
        # создаём роль с deny-view и назначаем reader'у
        role = models.Role(name=f"Денайлер {uuid.uuid4().hex[:6]}")
        db.add(role)
        db.flush()
        snap.role_id = role.id
        db.add(snap)
        db.flush()
        db.add(models.PermissionEntry(snapshot_id=snap.id, permission="view", state="deny"))
        db.add(models.UserRole(user_id=reader.id, role_id=role.id))
        db.commit()

        out_sa = retrieve_chunks(db, _principal(db, author, is_super=True),
                                 q="паркетчик", k=10)
        assert out_sa["total"] >= 1

        out_reader = retrieve_chunks(db, _principal(db, reader, is_super=False),
                                     q="паркетчик", k=10)
        assert out_reader["total"] == 0  # deny → материала нет в выдаче

    def test_draft_visibility_by_author(self, db, rag_query_on):
        """§7.3: черновик виден только автору/процессу — чанки не утекают."""
        from app.use_cases.rag.retrieve import retrieve_chunks

        author = _user(db, "Автор Черновика")
        stranger = _user(db, "Чужой Пользователь")
        g = _make_group(db)
        m = _material(db, g, author, "Черновик паркетного стандарта",
                      "Черновые паркетные тезисы. " * 40, status="draft")
        _index(db, m)

        out_author = retrieve_chunks(db, _principal(db, author, is_super=False),
                                     q="паркетные", k=10)
        assert out_author["total"] >= 1

        out_stranger = retrieve_chunks(db, _principal(db, stranger, is_super=False),
                                       q="паркетные", k=10)
        assert out_stranger["total"] == 0

    def test_group_filter_subtree_and_exact(self, db, rag_query_on):
        """§7.2: поддерево (path-префикс) vs строго группа."""
        from app.use_cases.rag.retrieve import retrieve_chunks

        u = _user(db, "Пользователь Группфилтр")
        principal = _principal(db, u, is_super=True)
        parent = _make_group(db, name="Родитель Поиска")
        child = _make_group(db, name="Ребёнок Поиска", parent_id=parent.id)
        m_parent = _material(db, parent, u, "Материал родителя",
                             "Паркетные работы родителя. " * 40)
        m_child = _material(db, child, u, "Материал ребёнка",
                            "Паркетные работы ребёнка. " * 40)
        _index(db, m_parent)
        _index(db, m_child)

        # Поддерево: оба
        out = retrieve_chunks(db, principal, q="паркетные", group_id=str(parent.id),
                              include_subgroups=True, k=20)
        got = {it["material"]["id"] for it in out["items"]}
        assert str(m_parent.id) in got and str(m_child.id) in got

        # Строго группа: только родительский
        out2 = retrieve_chunks(db, principal, q="паркетные", group_id=str(parent.id),
                               include_subgroups=False, k=20)
        got2 = {it["material"]["id"] for it in out2["items"]}
        assert str(m_parent.id) in got2 and str(m_child.id) not in got2

    def test_dedup_by_material(self, db, rag_query_on):
        """§9-4: один материал — один чанк в выдаче."""
        from app.use_cases.rag.retrieve import retrieve_chunks

        u = _user(db, "Пользователь Дедуп")
        principal = _principal(db, u, is_super=True)
        g = _make_group(db)
        m = _material(db, g, u, "Длинный материал",
                      "\n\n".join(f"Паркетный абзац {i}. " + "т" * 150 for i in range(30)))
        _index(db, m)
        out = retrieve_chunks(db, principal, q="паркетный", k=20)
        mids = [it["material"]["id"] for it in out["items"]]
        assert len(mids) == len(set(mids))  # дедуп: повторов нет

    def test_k_limit_validation(self, db, rag_query_on):
        from app.use_cases.rag.retrieve import retrieve_chunks
        from app.use_cases.errors import DomainError

        u = _user(db, "Пользователь Лимит")
        principal = _principal(db, u, is_super=True)
        with pytest.raises(DomainError):
            retrieve_chunks(db, principal, q="паркет", k=21)
        with pytest.raises(DomainError):
            retrieve_chunks(db, principal, q="паркет", k=0)

    def test_hybrid_merges_fts(self, db, rag_query_on):
        """§9-3: hybrid работает; материалы FTS-потока попадают в выдачу."""
        from app.use_cases.rag.retrieve import retrieve_chunks

        u = _user(db, "Пользователь Гибрид")
        principal = _principal(db, u, is_super=True)
        g = _make_group(db)
        m1 = _material(db, g, u, "Регламент гибридных работ",
                       "Гибридные паркетные тезисы. " * 40)
        _index(db, m1)
        out = retrieve_chunks(db, principal, q="гибридные", k=10, mode="hybrid")
        assert out["mode"] == "hybrid"
        assert any(it["material"]["id"] == str(m1.id) for it in out["items"])


class TestSearchTypes:
    def test_vector_type_returns_materials(self, db, rag_query_on):
        """§7.1-1: GET /search?search_type=vector — материалы (не чанки)."""
        from app.use_cases.materials.search_materials import search_materials

        u = _user(db, "Пользователь Сёрчвектор")
        principal = _principal(db, u, is_super=True)
        g = _make_group(db)
        m = _material(db, g, u, "Материал векторного поиска",
                      "Паркетные векторные тезисы. " * 40)
        _index(db, m)
        out = search_materials(db, principal, q="паркетные", search_type="vector")
        assert out["total"] >= 1
        assert out["items"][0]["id"] == str(m.id)
        assert "group" in out["items"][0] or "name" in out["items"][0]

    def test_vector_type_has_score(self, db, rag_query_on):
        """Релевантность в UI (§7.7): каждый элемент vector-выдачи со чанками
        несёт score (1−dist, 0..1); у материала со чанками он есть всегда."""
        from app.use_cases.materials.search_materials import search_materials

        u = _user(db, "Пользователь Скорвектор")
        principal = _principal(db, u, is_super=True)
        g = _make_group(db)
        m = _material(db, g, u, "Скор векторного поиска",
                      "Паркетные скор-тезисы. " * 40)
        _index(db, m)
        out = search_materials(db, principal, q="паркетные", search_type="vector")
        assert out["total"] >= 1
        hit = next(i for i in out["items"] if i["id"] == str(m.id))
        assert isinstance(hit["score"], (int, float))
        assert 0.0 <= hit["score"] <= 1.0

    def test_hybrid_type(self, db, rag_query_on):
        from app.use_cases.materials.search_materials import search_materials

        u = _user(db, "Пользователь Сёрчгибрид")
        principal = _principal(db, u, is_super=True)
        g = _make_group(db)
        m = _material(db, g, u, "Материал гибридного поиска",
                      "Гибридный паркетный текст. " * 40)
        _index(db, m)
        out = search_materials(db, principal, q="гибридный", search_type="hybrid")
        assert out["total"] >= 1
        hit = next(i for i in out["items"] if i["id"] == str(m.id))
        # RRF-скор положителен и мал (потолок 2/(60+1) ≈ 0.0328)
        assert 0 < hit["score"] <= 2 / 61

    def test_fulltext_still_works(self, db):
        """Регресс: fulltext не тронут (SQLite ILIKE-ветка), score не отдаётся."""
        from app.use_cases.materials.search_materials import search_materials

        u = _user(db, "Пользователь Фуллтекст")
        principal = _principal(db, u, is_super=True)
        g = _make_group(db)
        _material(db, g, u, "Регламент паркетных работ", "Текст. " * 10)
        out = search_materials(db, principal, q="паркетных", search_type="fulltext")
        assert out["total"] >= 1
        assert all("score" not in i for i in out["items"])


class TestRetrieveAPI:
    def test_endpoint(self, db, client, rag_query_on):
        """POST /rag/retrieve: транспорт, deep_link, search_events пишутся."""
        u = db.execute(select(models.User).where(
            models.User.display_name == "Тестовый СА")).scalar_one()
        g = _make_group(db)
        m = _material(db, g, u, "Материал API-поиска",
                      "Паркетный API-текст. " * 40)
        _index(db, m)
        r = client.post("/api/v1/rag/retrieve", json={
            "query": "паркетный", "k": 5, "mode": "vector"})
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "vector"
        for it in body["items"]:
            assert it["deep_link"].startswith("/materials/")
        # search_events (§9-5)
        ev = db.execute(select(models.SearchEvent)).scalars().all()
        assert any("паркетный" in e.query_normalized for e in ev)

    def test_endpoint_requires_auth(self, db, client):
        # Транспорт подменяет аутентификацию фикстурой; проверяем валидацию тела
        r = client.post("/api/v1/rag/retrieve", json={"query": "", "k": 5})
        assert r.status_code == 400  # min_length → RequestValidationError → 400

    def test_k_over_limit_400(self, db, client):
        r = client.post("/api/v1/rag/retrieve", json={"query": "текст", "k": 25})
        assert r.status_code == 400  # Field le=20 → RequestValidationError → 400

    def test_search_type_vector_endpoint(self, db, client, rag_query_on):
        u = db.execute(select(models.User).where(
            models.User.display_name == "Тестовый СА")).scalar_one()
        g = _make_group(db)
        _material(db, g, u, "Регламент API-паркета", "Паркетный текст. " * 40)
        r = client.get("/api/v1/search", params={
            "q": "паркетный", "search_type": "vector"})
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    def test_search_type_bad_400(self, db, client):
        r = client.get("/api/v1/search", params={"q": "x", "search_type": "bm25"})
        assert r.status_code == 400
