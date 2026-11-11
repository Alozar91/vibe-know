# Хелпер API-окружения для тестов file_texts (вынесен, чтобы не тянуть фикстуры
# test_files_versions в тесты RAG-структур).
import uuid

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db import models
from app.main import app


def _setup_client(db, name="Тестовый СА"):
    """СА-клиент + группа/тип/материал (published). Возвращает (client, g, t, m)."""
    principal = models.User(keycloak_id=f"kc-{uuid.uuid4().hex[:8]}",
                            display_name=name)
    db.add(principal)
    db.commit()
    from app.api.deps import CurrentUser

    token_info = {"sub": principal.keycloak_id, "active": True}
    cu = CurrentUser(principal, token_info, True)

    def override():
        return cu

    app.dependency_overrides[get_current_user] = override
    client = TestClient(app)

    r = client.post("/api/v1/groups", json={"name": "Группа FT"})
    assert r.status_code == 201, r.text
    g = r.json()
    r = client.post("/api/v1/types", json={"name": "Тип FT", "attribute_ids": []})
    assert r.status_code == 201, r.text
    t = r.json()
    r = client.post("/api/v1/materials", json={
        "name": "Материал с файлом", "group_id": g["id"], "type_id": t["id"],
        "text_content": "",
    })
    assert r.status_code == 201, r.text
    m = r.json()
    return client, g, t, m
