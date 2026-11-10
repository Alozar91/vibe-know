# Тесты RAG-API СА (пост-MVP шаг [7]): CRUD конфигураций групп + валидация
# по реестру чанкеров + статус индексации (/admin/rag/status). Права: только
# СА (403 остальным); 404 — группа/настройка.
import uuid

from app.db import models


def _make_group(db, name="Группа RAG", parent_id=None):
    """Группа с materialized path из реальных id (resolve_config ищет по path!)."""
    parent_path = ""
    if parent_id:
        parent = db.get(models.Group, parent_id)
        parent_path = parent.path
    g = models.Group(name=name, normalized_name=name.lower(), parent_id=parent_id,
                     path="pending")
    db.add(g)
    db.flush()  # g.id известен
    g.path = f"{parent_path}{g.id}/"
    db.commit()
    return g


_type_cache: dict = {}
_user_cache: dict = {}


def _type_id(db):
    if "id" not in _type_cache:
        t = models.MaterialType(name=f"Тип RAG {uuid.uuid4().hex[:8]}")
        db.add(t)
        db.flush()
        _type_cache["id"] = t.id
        db.commit()
    return _type_cache["id"]


def _user_id(db):
    if "id" not in _user_cache:
        u = models.User(keycloak_id=f"kc-rag-{uuid.uuid4().hex[:8]}",
                        display_name="RAG Пользователь")
        db.add(u)
        db.flush()
        _user_cache["id"] = u.id
        db.commit()
    return _user_cache["id"]


def _make_material(db, group, name="Материал RAG", text="Текст материала.",
                   status="published"):
    m = models.Material(
        group_id=group.id, name=name, normalized_name=name.lower(),
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


class TestChunkersList:
    def test_requires_sa(self, db, as_user):
        c = as_user("Рядовой", is_super=False)
        r = c.get("/api/v1/admin/rag/chunkers")
        assert r.status_code == 403

    def test_list(self, db, client):
        r = client.get("/api/v1/admin/rag/chunkers")
        assert r.status_code == 200
        names = r.json()["chunkers"]
        for n in ("whole", "symbols", "recursive", "markdown"):
            assert n in names


class TestConfigCRUD:
    def test_get_missing_group_404(self, db, client):
        r = client.get(f"/api/v1/admin/rag/groups/{uuid.uuid4()}/config")
        assert r.status_code == 404

    def test_get_empty(self, db, client):
        g = _make_group(db)
        r = client.get(f"/api/v1/admin/rag/groups/{g.id}/config")
        assert r.status_code == 200
        body = r.json()
        assert body["own"] is None and body["effective"] is None
        assert "markdown" in body["chunkers"]

    def test_upsert_and_get(self, db, client):
        g = _make_group(db)
        r = client.put(f"/api/v1/admin/rag/groups/{g.id}/config",
                       json={"chunker": "markdown", "params": {"max_len": 900}})
        assert r.status_code == 200
        assert r.json()["chunker"] == "markdown"
        r2 = client.get(f"/api/v1/admin/rag/groups/{g.id}/config")
        body = r2.json()
        assert body["own"]["params"] == {"max_len": 900}
        assert body["effective"]["group_id"] == str(g.id)  # effective == own
        assert body["inherit_from"] is None

    def test_unknown_chunker_400(self, db, client):
        g = _make_group(db)
        r = client.put(f"/api/v1/admin/rag/groups/{g.id}/config",
                       json={"chunker": "no-such", "params": {}})
        assert r.status_code == 400
        assert "доступные" in r.json()["detail"].lower()

    def test_inherit_from_parent(self, db, client):
        """Подгруппа без своей настройки видит effective от родителя (§3.2)."""
        parent = _make_group(db, name="Родитель")
        child = _make_group(db, name="Ребёнок", parent_id=parent.id)
        client.put(f"/api/v1/admin/rag/groups/{parent.id}/config",
                   json={"chunker": "symbols", "params": {"size": 700}})
        r = client.get(f"/api/v1/admin/rag/groups/{child.id}/config")
        body = r.json()
        assert body["own"] is None
        assert body["effective"]["chunker"] == "symbols"
        assert body["inherit_from"] == str(parent.id)

    def test_child_overrides_parent(self, db, client):
        parent = _make_group(db, name="Родитель2")
        child = _make_group(db, name="Ребёнок2", parent_id=parent.id)
        client.put(f"/api/v1/admin/rag/groups/{parent.id}/config",
                   json={"chunker": "symbols", "params": {"size": 700}})
        client.put(f"/api/v1/admin/rag/groups/{child.id}/config",
                   json={"chunker": "recursive", "params": {"size": 300}})
        r = client.get(f"/api/v1/admin/rag/groups/{child.id}/config")
        body = r.json()
        assert body["own"]["chunker"] == "recursive"
        assert body["effective"]["chunker"] == "recursive"  # ближайшая — своя

    def test_delete_restores_inheritance(self, db, client):
        parent = _make_group(db, name="Родитель3")
        child = _make_group(db, name="Ребёнок3", parent_id=parent.id)
        client.put(f"/api/v1/admin/rag/groups/{parent.id}/config",
                   json={"chunker": "whole"})
        client.put(f"/api/v1/admin/rag/groups/{child.id}/config",
                   json={"chunker": "symbols"})
        r = client.delete(f"/api/v1/admin/rag/groups/{child.id}/config")
        assert r.status_code == 204
        body = client.get(f"/api/v1/admin/rag/groups/{child.id}/config").json()
        assert body["own"] is None
        assert body["effective"]["chunker"] == "whole"  # снова от родителя

    def test_delete_missing_404(self, db, client):
        r = client.delete(f"/api/v1/admin/rag/groups/{uuid.uuid4()}/config")
        assert r.status_code == 404

    def test_requires_sa_for_write(self, db, as_user):
        g = _make_group(db)
        c = as_user("Не-СА", is_super=False)
        r = c.put(f"/api/v1/admin/rag/groups/{g.id}/config",
                  json={"chunker": "whole"})
        assert r.status_code == 403


class TestIndexStatus:
    def test_requires_sa(self, db, as_user):
        c = as_user("Рядовой", is_super=False)
        r = c.get("/api/v1/admin/rag/status")
        assert r.status_code == 403

    def test_empty(self, db, client):
        r = client.get("/api/v1/admin/rag/status")
        assert r.status_code == 200
        body = r.json()
        assert body["counts"] == {}
        assert body["problems"] == []
        assert body["total_chunks"] == 0

    def test_counts_and_problems(self, db, client):
        """Счётчики по rag_state + проблемные (pending/error) в problems."""
        g = _make_group(db)
        m_ok = _make_material(db, g, name="ОК-материал")
        m_ok.rag_state = "indexed"
        m_err = _make_material(db, g, name="Ошибка-материал")
        m_err.rag_state = "error"
        m_pend = _make_material(db, g, name="Очередь-материал")
        m_pend.rag_state = "pending"
        db.commit()

        r = client.get("/api/v1/admin/rag/status")
        assert r.status_code == 200
        body = r.json()
        assert body["counts"] == {"indexed": 1, "error": 1, "pending": 1}
        ids = {p["id"] for p in body["problems"]}
        assert ids == {str(m_err.id), str(m_pend.id)}
        assert all(p["state"] in ("pending", "error") for p in body["problems"])
        # indexed-материал не в problems, но в счётчике
        assert str(m_ok.id) not in ids
