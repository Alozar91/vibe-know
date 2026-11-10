# -*- coding: utf-8 -*-
"""Сид демонстрационных данных стенда (идемпотентный).

Воспроизводит демо-набор после чистки (cleanup.sql): пользователи Keycloak →
провижининг в БД (direct grant kb-cli + GET /me) → роли → справочники/атрибуты/
типы → группы с иерархией → снапшоты прав на группы → материалы во всех
статусах, включая мастер-подчинённую цепочку (мастер + адаптация + перевод).

Запуск из deploy/ (только stdlib):
    python seed_demo.py            # сеет недостающее; существующее не трогает
    python seed_demo.py --check    # только отчёт о текущем состоянии

Примечания (подробности — AGENTS.md «Repo quirks»):
- после cleanup.sql СА стенда (ivanov) теряет is_super — вернуть прямым INSERT
  в user_roles (роль хранится в roles; см. README §7);
- draft→in_review требует файл (FR-028): скрипт сам грузит .txt и перечитывает
  версию (If-Match) после загрузки;
- Рецензент без review-права на группу получает 404 по предикату §3.2 — скрипт
  сеет права до материалов.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent
ENV_PATH = DEPLOY / ".env"
KC = "http://localhost:8080/realms/kb/protocol/openid-connect/token"
API = "http://localhost:8001/api/v1"
CHECK = "--check" in sys.argv

# ------------------------------- основа ------------------------------------


def load_env() -> dict:
    env = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


def api_token(env: dict, username: str) -> str:
    """Direct grant kb-cli: вход = провижининг пользователя в БД (при introspection
    на /me — email_cache и профиль)."""
    body = urllib.parse.urlencode({
        "grant_type": "password", "client_id": "kb-cli",
        "client_secret": env["KB_CLI_CLIENT_SECRET"],
        "username": username, "password": env["KB_TEST_PASSWORD"],
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(KC, data=body)) as r:
        return json.load(r)["access_token"]


def api(method: str, path: str, at: str, payload=None, if_match: str | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": "Bearer " + at, "Content-Type": "application/json"}
    if if_match:
        headers["If-Match"] = if_match
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


# --------------------------- keycloak (kcadm) -------------------------------


def kcadm(script_body: str, env: dict) -> tuple[int, str]:
    """Один exec в keycloak: сначала config credentials, затем команда."""
    full = (
        f'/opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 '
        f'--realm master --user {env["KC_BOOTSTRAP_ADMIN_USERNAME"]} '
        f'--password "{env["KC_BOOTSTRAP_ADMIN_PASSWORD"]}" >/dev/null 2>&1\n'
        + script_body + "\n"
    )
    r = subprocess.run(
        ["docker", "compose", "exec", "-T", "keycloak", "/bin/sh", "-c", full],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=DEPLOY,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def kc_user_id(env, username: str) -> str | None:
    code, out = kcadm(
        "/opt/keycloak/bin/kcadm.sh get users -r kb -q username=" + username +
        " --fields id --format csv --noquotes | tail -1", env)
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    return lines[-1] if lines and lines[-1] != "id" else None


def kc_create_user(env, username, email, first, last) -> str | None:
    """Создание по частям: comma-join в одном -s ломается (AGENTS.md);
    ASCII-имя — кириллица в firstName/lastName тоже отвергается."""
    ascii_first = first if first.isascii() else first.encode("ascii", "ignore").decode() or "User"
    ascii_last = last if last.isascii() else last.encode("ascii", "ignore").decode() or "User"
    code, out = kcadm(
        "/opt/keycloak/bin/kcadm.sh create users -r kb"
        " -s username=" + username + " -s enabled=true -i", env)
    uid = out.strip().splitlines()[-1] if out.strip() else None
    if not uid or len(uid) < 32 or "error" in uid.lower():
        return None
    for kv in ("email=" + email, "firstName=" + (ascii_first or username),
               "lastName=" + (ascii_last or username), "emailVerified=true"):
        kcadm("/opt/keycloak/bin/kcadm.sh update users/" + uid + " -r kb -s " + kv, env)
    return uid


def kc_set_password(env, username: str) -> bool:
    code, _ = kcadm(
        "/opt/keycloak/bin/kcadm.sh set-password -r kb --username " + username +
        ' --new-password "' + env["KB_TEST_PASSWORD"] + '"', env)
    return code == 0


# ------------------------------ сид-данные ----------------------------------

USERS = [  # (username, email, first, last, роль | None)
    ("ivanov", "ivanov@example.local", "Иван", "Иванов", "Системный администратор"),
    ("merch", "sermer@list.ru", "Sergey", "M", "Системный администратор"),
    ("petrov", "petrov@example.local", "Пётр", "Петров", "Рецензент"),
    ("sidorov", "sidorov@example.local", "Андрей", "Сидоров", "Автор"),
    ("smirnova", "smirnova@example.local", "Ольга", "Смирнова", "Читатель"),
    ("kuznetsov", "kuznetsov@example.local", "Дмитрий", "Кузнецов", None),
]

GROUPS = [  # (name, parent | None)
    ("Корпоративные регламенты", None),
    ("ИТ", "Корпоративные регламенты"),
    ("Информационная безопасность", "Корпоративные регламенты"),
    ("Управление персоналом", None),
    ("Онбординг", "Управление персоналом"),
    ("Администрирование", "Управление персоналом"),
]

# Снапшоты прав на группы: (группа, роль | None=«Все пользователи», [(perm, state)])
GROUP_PERMS = [
    ("Корпоративные регламенты", None, [("view", "allow")]),
    ("ИТ", "Автор", [("view", "allow"), ("create", "allow"), ("edit", "allow"), ("delete", "allow")]),
    ("ИТ", "Рецензент", [("review", "allow")]),
    ("ИТ", "Читатель", [("view", "allow")]),
    ("Информационная безопасность", "Автор", [("view", "allow"), ("create", "allow"), ("edit", "allow")]),
    ("Информационная безопасность", "Рецензент", [("view", "allow"), ("review", "allow")]),
    ("Информационная безопасность", "Читатель", [("view", "allow")]),
    ("Управление персоналом", "Автор", [("view", "allow"), ("create", "allow"), ("edit", "allow")]),
    ("Онбординг", "Рецензент", [("view", "allow"), ("review", "allow")]),
    ("Онбординг", "Читатель", [("view", "allow")]),
]

MATERIALS = [  # (name, группа, тип, код, текст, целевой статус)
    ("Регламент резервного копирования", "ИТ", "Регламент", "IT-BKP-001",
     "Регламент резервного копирования ИТ-систем.\n\n1. Резервная копия создаётся ежедневно в 02:00.\n"
     "2. Хранение: 30 дней, инкрементально.\n3. Восстановление проверяется ежеквартально.",
     "published"),
    ("Регламент доступа к сети", "ИТ", "Регламент", "IT-NET-001",
     "Регламент разграничения доступа к корпоративной сети.\nVPN, MFA, гостевой доступ.",
     "published"),
    ("Инструкция настройки VPN", "ИТ", "Инструкция", "IT-VPN-001",
     "Пошаговая инструкция подключения VPN.\n1. Установить клиент. 2. Импортировать сертификат. "
     "3. Подключиться к vpn.example.local.", "in_review"),
    ("Регламент реагирования на инциденты", "Информационная безопасность", "Регламент", "IB-INC-001",
     "Регламент реагирования на инциденты ИБ.\nКлассификация инцидентов, эскалация, SLA.",
     "approved"),
    ("Памятка по фишингу", "Информационная безопасность", "Информационный материал", None,
     "Как распознать фишинговое письмо: подозрительный отправитель, срочность, ссылки.",
     "published"),
    ("Регламент приёма сотрудника", "Онбординг", "Регламент", "HR-ONB-001",
     "Процедура приёма нового сотрудника: заявка, учётные записи, рабочее место.",
     "published"),
    ("Положение об отпусках", "Управление персоналом", "Информационный материал", None,
     "Порядок предоставления отпусков: график, заявление, перенос.",
     "draft"),
]


# -------------------------------- шаги --------------------------------------


def step_users(env) -> None:
    print("== Пользователи Keycloak ==")
    for username, email, first, last, _role in USERS:
        uid = kc_user_id(env, username)
        if uid:
            print(f"   = {username} (kc {uid[:8]})")
        else:
            uid = kc_create_user(env, username, email, first, last)
            print(f"   + {username} (kc {(uid or 'FAIL')[:8]})")
        if uid and not kc_set_password(env, username):
            print(f"   ! пароль {username} не установлен")


def restore_sa_direct(env) -> None:
    """После cleanup.sql user_roles пуст → ivanov без is_super (AGENTS.md).

    Роли в roles сохранены — INSERT напрямую (до него API ролей недоступен:
    GET /users требует СА)."""
    sql = ("INSERT INTO user_roles (user_id, role_id) "
           "SELECT u.id, r.id FROM users u, roles r "
           "WHERE u.email_cache = 'ivanov@example.local' AND u.is_service = false "
           "AND r.name = 'Системный администратор' "
           "AND NOT EXISTS (SELECT 1 FROM user_roles x WHERE x.user_id = u.id AND x.role_id = r.id);")
    subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "kb", "-d", "kb", "-c", sql],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=DEPLOY,
    )


def step_provision_roles(env) -> dict:
    """Провижининг в БД (вход) + роли. Возвращает {role_name: role_id}."""
    print("== Провижининг + роли ==")
    tokens = {}
    for username, *_ in USERS:
        try:
            tokens[username] = api_token(env, username)
            api("GET", "/me", tokens[username])  # провижининг + email_cache
        except urllib.error.HTTPError as e:
            print(f"   ! вход {username}: {e.code}")

    # СА стенда после чистки теряется — восстановить до обращения к /users
    st, me = api("GET", "/me", tokens["ivanov"])
    if not me.get("is_super"):
        restore_sa_direct(env)
        st, me = api("GET", "/me", tokens["ivanov"])
        print(f"   СА ivanov восстановлен (is_super={me.get('is_super')})")

    at = tokens["ivanov"]
    st, roles = api("GET", "/roles", at)
    R = {r["name"]: r["id"] for r in roles}
    st, users = api("GET", "/users?per_page=100", at)
    # Сопоставление по email (kcadm создаёт с ASCII-именем — кириллица
    # в firstName/lastName отвергается Keycloak, см. AGENTS.md).
    U = {u["email_cache"]: u["id"] for u in users["items"] if u.get("email_cache")}

    for username, email, _first, _last, role in USERS:
        if email not in U:
            print(f"   ! {username} не провиженен в БД (вход не удался?)")
            continue
        if role is None:
            print(f"   - {username}: без роли (проверка оффера)")
            continue
        st, _ = api("PUT", f"/users/{U[email]}/roles/{R[role]}", at)
        print(f"   роль {role} → {username}: {st}")
    return R


def ensure_snapshot(at, group_id, role_id, entries, label) -> None:
    want = [{"permission": p, "state": s} for p, s in entries]
    st, existing = api("GET", f"/groups/{group_id}/permissions", at)
    for snap in existing or []:
        if snap.get("role_id") == role_id and snap.get("entries") == want:
            print(f"   = {label}")
            return
    st, body = api("POST", f"/groups/{group_id}/permissions", at,
                   {"role_id": role_id, "entries": want})
    print(f"   {'+' if st == 201 else '!'} {label}: {st}")


def step_refs_groups(env) -> dict:
    print("== Справочники/атрибуты/типы ==")
    at = api_token(env, "ivanov")

    # справочник «Языки»
    st, dicts = api("GET", "/dictionaries", at)
    dict_id = next((d["id"] for d in dicts if d["name"] == "Языки"), None)
    lang_dv = {}
    if dict_id:
        d = next(d for d in dicts if d["name"] == "Языки")
        lang_dv = {v["value"]: v["id"] for v in d.get("value_items", [])}
    else:
        st, d = api("POST", "/dictionaries", at, {"name": "Языки"})
        assert st == 201, (st, d)
        dict_id = d["id"]
    for val in ("Русский", "English"):
        if val not in lang_dv:
            st, v = api("POST", f"/dictionaries/{dict_id}/values", at, {"value": val})
            assert st == 201, (st, v)
            lang_dv[val] = v["id"]
    print(f"   словарь «Языки»: {len(lang_dv)} значений")

    # атрибуты
    st, attrs = api("GET", "/attributes", at)
    A = {a["name"]: a["id"] for a in attrs}
    for name, vt, req, did in (
        ("Язык", "dictionary", False, dict_id),
        ("Код документа", "string", True, None),
        ("Дата утверждения", "date", False, None),
        ("Ссылка на источник", "url", False, None),
    ):
        if name not in A:
            body = {"name": name, "value_type": vt, "is_required": req}
            if did:
                body["dictionary_id"] = did
            st, a = api("POST", "/attributes", at, body)
            assert st == 201, (st, a, name)
            A[name] = a["id"]
    print(f"   атрибуты: {len(A)}")

    # типы + привязка «Язык» к Инструкции
    st, types = api("GET", "/types", at)
    T = {t["name"]: t["id"] for t in types}
    for tname, attr_names in (
        ("Регламент", ["Код документа", "Дата утверждения"]),
        ("Инструкция", ["Код документа", "Дата утверждения"]),
        ("Информационный материал", []),
    ):
        if tname not in T:
            st, t = api("POST", "/types", at,
                        {"name": tname, "attribute_ids": [A[n] for n in attr_names]})
            assert st == 201, (st, t, tname)
            T[tname] = t["id"]
    st, _ = api("POST", f"/types/{T['Инструкция']}/attributes/{A['Язык']}", at)
    print(f"   типы: {list(T)}")

    # группы (плоская выборка с детьми)
    st, groups = api("GET", "/groups", at)

    def flat(items):
        for g in items:
            yield g
            yield from flat(g.get("children") or [])

    G = {g["name"]: g["id"] for g in flat(groups)}
    for name, parent in GROUPS:
        if name not in G:
            body = {"name": name}
            if parent:
                body["parent_id"] = G[parent]
            st, g = api("POST", "/groups", at, body)
            assert st == 201, (st, g, name)
            G[name] = g["id"]
    print(f"   группы: {len(G)}")

    # права на группы
    print("== Права на группы ==")
    st, roles = api("GET", "/roles", at)
    R = {r["name"]: r["id"] for r in roles}
    for grp, role, entries in GROUP_PERMS:
        ensure_snapshot(at, G[grp], R.get(role) if role else None, entries,
                        f"{grp}: {role or 'Все пользователи'} — " + ", ".join(f"{p}={s}" for p, s in entries))

    return {"at": at, "G": G, "T": T, "A": A, "lang_dv": lang_dv}


def upload_file(at, mid, filename, content: bytes):
    boundary = "----kbseedboundary1234"
    part = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{API}/materials/{mid}/file", data=part, method="POST",
        headers={"Authorization": "Bearer " + at,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def drive_to(at_sa, tok, mid, target: str) -> None:
    """Ведёт материал по цепочке draft → in_review → approved → published."""
    path = {"draft": 0, "in_review": 1, "approved": 2, "published": 3}
    who = {"in_review": "sidorov", "approved": "petrov", "published": "ivanov"}
    for step in ("in_review", "approved", "published"):
        st, cur = api("GET", f"/materials/{mid}", at_sa)
        if path.get(cur["status"], 0) >= path[target]:
            return
        if path.get(cur["status"], 0) >= path[step]:
            continue
        if cur["status"] == "draft" and step == "in_review":
            # FR-028: файл обязателен; загрузка поднимает версию → перечитать
            upload_file(tok["sidorov"], mid, cur["name"] + ".txt",
                        (cur.get("text_content") or "Демонстрационный документ стенда.")
                        .encode("utf-8"))
            st, cur = api("GET", f"/materials/{mid}", at_sa)
        st, r = api("POST", f"/materials/{mid}/transitions", tok[who[step]],
                    {"to_status": step}, if_match=str(cur["version"]))
        if st != 200:
            print(f"      ! переход {step}: {st} {r}")
            return


def step_materials(env, refs) -> None:
    print("== Материалы ==")
    at = refs["at"]
    tok = {"sidorov": api_token(env, "sidorov"),
           "petrov": api_token(env, "petrov"),
           "ivanov": at}

    def find_in(group_id, name):
        st, lst = api("GET", f"/materials?group_id={group_id}&per_page=100", at)
        return next((m for m in lst.get("items", []) if m["name"] == name), None)

    ids = {}
    for name, grp, tp, code, text, target in MATERIALS:
        m = find_in(refs["G"][grp], name)
        if m is None:
            av = [{"attribute_id": refs["A"]["Код документа"], "values": [code]}] if code else []
            st, m = api("POST", "/materials", tok["sidorov"], {
                "name": name, "group_id": refs["G"][grp], "type_id": refs["T"][tp],
                "text_content": text, "attribute_values": av,
            })
            assert st == 201, (st, m, name)
            print(f"   + {name}")
        else:
            print(f"   = {name} ({m['status']})")
        ids[name] = m["id"]
        drive_to(at, tok, m["id"], target)

    # мастер-подчинённая цепочка от published-мастера
    master_id = ids["Регламент резервного копирования"]
    st, lst = api("GET", "/materials?per_page=100", at)
    have = {m["name"] for m in lst.get("items", [])}

    if "Регламент резервного копирования Адаптация" not in have:
        st, ch = api("POST", f"/materials/{master_id}/children", tok["sidorov"],
                     {"kind": "adaptation", "group_id": refs["G"]["Онбординг"]})
        assert st == 201, (st, ch)
        print("   + адаптация (подчинённый, Онбординг)")
    else:
        print("   = адаптация уже есть")

    if "Регламент резервного копирования (Перевод, ENG)" not in have:
        st, ch = api("POST", f"/materials/{master_id}/children", tok["sidorov"],
                     {"kind": "translation", "group_id": refs["G"]["ИТ"],
                      "language_id": refs["lang_dv"]["English"]})
        assert st == 201, (st, ch)
        print("   + перевод (подчинённый, ИТ, English)")
    else:
        print("   = перевод уже есть")


def report(env) -> None:
    at = api_token(env, "ivanov")
    st, lst = api("GET", "/materials?per_page=100", at)
    print("\n== Отчёт ==")
    print("материалов:", lst["total"])
    for m in sorted(lst["items"], key=lambda x: x["name"]):
        print("  -", m["name"], "|", m["status"])
    st, groups = api("GET", "/groups", at)

    def flat(items):
        for g in items:
            yield g
            yield from flat(g.get("children") or [])

    print("групп:", len(list(flat(groups))))
    st, users = api("GET", "/users?per_page=100", at)
    for u in users["items"]:
        print("  -", u["display_name"], "→", u["roles"] or "(без роли)")


def main() -> None:
    env = load_env()
    if CHECK:
        report(env)
        return
    step_users(env)
    step_provision_roles(env)
    refs = step_refs_groups(env)
    step_materials(env, refs)
    report(env)
    print("\nГотово. Вход: merch / ivanov, пароль KB_TEST_PASSWORD (.env).")


if __name__ == "__main__":
    main()
