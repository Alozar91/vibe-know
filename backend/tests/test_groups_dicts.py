# Этап 3: группы (US-052), типы/атрибуты (US-030), справочники/теги (US-033).
# Фикстуры — conftest.py (общая in-memory БД, CA-пользователь по умолчанию).


def _mk_group(client, name, parent_id=None):
    r = client.post("/api/v1/groups", json={"name": name, "parent_id": parent_id})
    assert r.status_code == 201, r.text
    return r.json()


# --- US-052: группы ---

def test_group_create_root_and_child(client):
    """US-052 шаг 1: корневая и вложенная (вложенность не ограничена, FR-016)."""
    root = _mk_group(client, "Нормативы")
    child = _mk_group(client, "Фармакопея", parent_id=root["id"])
    sub = _mk_group(client, "ГОСТ", parent_id=child["id"])
    assert child["parent_id"] == root["id"]
    assert sub["path"].startswith(root["path"]) and sub["path"].endswith("/")
    assert "//" not in sub["path"]  # каноничный path без двойных слэшей


def test_group_duplicate_sibling_blocked(client):
    """US-052 шаг 2 / A1: дубликат среди сиблингов блокируется (без регистра/пробелов)."""
    root = _mk_group(client, "Нормативы")
    _mk_group(client, "ГОСТ", parent_id=root["id"])
    # тот же регистр/пробелы — конфликт
    r = client.post("/api/v1/groups", json={"name": "гост ", "parent_id": root["id"]})
    assert r.status_code == 409
    # в другой ветке — разрешено (FR-017: уникальность только среди сиблингов)
    root2 = _mk_group(client, "Инструкции")
    r2 = client.post("/api/v1/groups", json={"name": "ГОСТ", "parent_id": root2["id"]})
    assert r2.status_code == 201


def test_group_rename(client):
    """US-052 шаг 3: переименование; path не меняется (FR-023)."""
    g = _mk_group(client, "Старое")
    old_path = g["path"]
    r = client.patch(f"/api/v1/groups/{g['id']}", json={"name": "Новое"})
    assert r.status_code == 200
    assert r.json()["name"] == "Новое" and r.json()["path"] == old_path


def test_group_delete_empty_hard(client):
    """US-052 шаг 4: пустая группа — физическое удаление."""
    g = _mk_group(client, "Пустая")
    r = client.delete(f"/api/v1/groups/{g['id']}")
    assert r.status_code == 200 and r.json()["mode"] == "hard"
    # карточка больше не находится
    assert client.get(f"/api/v1/groups/{g['id']}").status_code == 404


def test_group_delete_nonempty_soft(client):
    """US-052 шаг 5: непустая ветка — soft-delete всей ветки."""
    root = _mk_group(client, "Ветка")
    _mk_group(client, "Под", parent_id=root["id"])
    r = client.delete(f"/api/v1/groups/{root['id']}")
    assert r.status_code == 200 and r.json()["mode"] == "soft" and r.json()["subtree_count"] == 2
    # скрыты из дерева
    tree_names = [x["name"] for x in client.get("/api/v1/groups").json()]
    assert "Ветка" not in tree_names
    # но видны в служебном списке (СА)
    deleted = client.get("/api/v1/groups/deleted").json()
    assert any(x["name"] == "Ветка" for x in deleted)


def test_group_name_freed_after_delete(client):
    """FR-022: названия освобождаются (soft-удалённая не мешает созданию)."""
    g = _mk_group(client, "Освобождаемая")
    client.delete(f"/api/v1/groups/{g['id']}")
    r = client.post("/api/v1/groups", json={"name": "Освобождаемая"})
    assert r.status_code == 201


def test_group_name_too_long(client):
    """FR-017: > 255 символов — NAME_TOO_LONG."""
    r = client.post("/api/v1/groups", json={"name": "х" * 256})
    assert r.status_code == 400 and r.json()["code"] == "NAME_TOO_LONG"


def test_group_requires_super(as_user):
    """FR-104/US-052: CRUD групп — только СА."""
    c = as_user("Просто юзер", is_super=False)
    assert c.post("/api/v1/groups", json={"name": "x"}).status_code == 403
    assert c.delete("/api/v1/groups/00000000-0000-0000-0000-000000000000").status_code == 403


# --- US-030: типы и атрибуты ---

def test_attribute_create_and_immutability(client):
    """US-030 шаг 1/3: атрибут создан; value_type/is_multivalue неизменяемы (FR-045)."""
    r = client.post("/api/v1/attributes", json={
        "name": "Действующее вещество", "value_type": "string", "is_multivalue": True,
    })
    assert r.status_code == 201
    aid = r.json()["id"]
    # правка только is_required/display_order; value_type не в схеме PATCH — не меняется
    r2 = client.patch(f"/api/v1/attributes/{aid}", json={"is_required": True, "display_order": 5})
    assert r2.status_code == 200 and r2.json()["is_required"] is True
    assert r2.json()["value_type"] == "string" and r2.json()["is_multivalue"] is True


def test_attribute_multivalue_only_for_allowed_types(client):
    """FR-044: многозначность — только string/url/dictionary."""
    r = client.post("/api/v1/attributes", json={
        "name": "Числовое", "value_type": "number", "is_multivalue": True,
    })
    assert r.status_code == 400


def test_attribute_requires_dictionary(client):
    """LLD §2.2: value_type='dictionary' → dictionary_id обязателен."""
    r = client.post("/api/v1/attributes", json={"name": "Язык", "value_type": "dictionary"})
    assert r.status_code == 400
    d = client.post("/api/v1/dictionaries", json={"name": "Языки"}).json()
    r2 = client.post("/api/v1/attributes", json={
        "name": "Язык", "value_type": "dictionary", "dictionary_id": d["id"],
    })
    assert r2.status_code == 201


def test_type_with_attributes_limit(client, db):
    """US-030 шаг 2 + FR-044: ≤ 50 атрибутов на тип."""
    attrs = []
    for i in range(51):
        attrs.append(client.post("/api/v1/attributes", json={
            "name": f"Атрибут {i}", "value_type": "string",
        }).json()["id"])
    t = client.post("/api/v1/types", json={"name": "Описание препарата", "attribute_ids": attrs[:50]})
    assert t.status_code == 201 and len(t.json()["attributes"]) == 50
    # 51-й — отказ
    t2 = client.post("/api/v1/types", json={"name": "Второй", "attribute_ids": attrs})
    assert t2.status_code == 409 and t2.json()["code"] == "ATTRIBUTES_LIMIT_EXCEEDED"


def test_type_delete_in_use_guard(client):
    """US-030 шаг 4 (FR-050): до этапа 4 материалов нет — тип удаляется физически."""
    t = client.post("/api/v1/types", json={"name": "Временный"}).json()
    r = client.delete(f"/api/v1/types/{t['id']}")
    assert r.status_code == 204


def test_unbind_attribute_keeps_values(client):
    """US-030 шаг 5 (FR-051): исключение из типа — привязка удалена, атрибут жив."""
    a = client.post("/api/v1/attributes", json={"name": "Исключаемый", "value_type": "string"}).json()
    t = client.post("/api/v1/types", json={"name": "Тип с искл.", "attribute_ids": [a["id"]]}).json()
    r = client.delete(f"/api/v1/types/{t['id']}/attributes/{a['id']}")
    assert r.status_code == 204
    # сам атрибут остался в пуле
    assert any(x["id"] == a["id"] for x in client.get("/api/v1/attributes").json())


# --- US-033: справочники и теги ---

def test_dictionary_flow(client):
    """US-033 шаг 1/4: справочник + значения; дубликат значения отклоняется."""
    d = client.post("/api/v1/dictionaries", json={"name": "Язык"}).json()
    v1 = client.post(f"/api/v1/dictionaries/{d['id']}/values", json={"value": "Русский"})
    assert v1.status_code == 201
    dup = client.post(f"/api/v1/dictionaries/{d['id']}/values", json={"value": "Русский "})
    assert dup.status_code == 409


def test_tag_flow_and_merge(client):
    """US-033 шаг 2–4: теги, переименование-слияние (FR-053), удаление (FR-054)."""
    t1 = client.post("/api/v1/tags", json={"name": "фармакология"}).json()
    t2 = client.post("/api/v1/tags", json={"name": "Pharmacology"}).json()
    # дубликат
    assert client.post("/api/v1/tags", json={"name": "фармакология"}).status_code == 409
    # слияние t2 → t1 (материалов нет — t2 просто удаляется)
    r = client.post(f"/api/v1/tags/{t2['id']}:merge", json={"target_id": t1["id"]})
    assert r.status_code == 200 and r.json()["merged_into"] == t1["id"]
    tags = {x["name"] for x in client.get("/api/v1/tags").json()}
    assert "Pharmacology" not in tags and "фармакология" in tags
    # удаление неиспользуемого
    assert client.delete(f"/api/v1/tags/{t1['id']}").status_code == 204


def test_tag_autocomplete(client):
    """US-031 шаг 4 (FR-052): автодополнение по префиксу."""
    for n in ("фармакология", "фармакокинетика", "химия"):
        client.post("/api/v1/tags", json={"name": n})
    r = client.get("/api/v1/tags?q=фарм")
    names = {x["name"] for x in r.json()}
    assert names == {"фармакология", "фармакокинетика"}
