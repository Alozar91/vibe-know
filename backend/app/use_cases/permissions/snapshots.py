# Use-case: снапшоты прав на объекте (FR-099/100/102/105, US-044) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, not_found
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.permissions.eff import PERMISSIONS_CATALOG
from app.use_cases.permissions.cache import commit_rights

STATES = ("allow", "deny", "unset")  # FR-102: Разрешить/Запретить/Не задано


def _validate_object(db: Session, object_type: str, object_id: str):
    if object_type not in ("group", "material"):
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="object_type должен быть group или material")
    oid = parse_uuid(object_id)
    if oid is None:
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Некорректный object_id")
    if object_type == "group":
        ok = db.execute(select(models.Group.id).where(models.Group.id == oid)).first()
    else:
        ok = db.execute(select(models.Material.id).where(models.Material.id == oid)).first()
    if ok is None:
        raise not_found("Объект не найден")
    return oid


def _validate_entries(entries: list[dict]) -> list[tuple[str, str]]:
    """[(permission, state)]: каталог FR-106; state allow|deny|unset (unset = удалить)."""
    out = []
    for e in entries or []:
        perm = str(e.get("permission", ""))
        state = str(e.get("state", ""))
        if perm not in PERMISSIONS_CATALOG:
            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail=f"Неизвестное право: {perm}")
        if state not in STATES:
            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail="state должен быть allow|deny|unset")
        out.append((perm, state))
    return out


def list_snapshots(db: Session, is_super: bool, object_type: str, object_id: str) -> list[dict]:
    """Снапшоты объекта с составом (US-044 просмотр)."""
    require_super(is_super)
    oid = _validate_object(db, object_type, object_id)
    rows = db.execute(
        select(models.PermissionSnapshot)
        .where(
            models.PermissionSnapshot.object_type == object_type,
            models.PermissionSnapshot.object_id == oid,
        )
        .order_by(models.PermissionSnapshot.created_at)
    ).scalars().all()
    return [_to_out(s) for s in rows]


def _to_out(s: models.PermissionSnapshot) -> dict:
    return {
        "id": str(s.id),
        "object_type": str(s.object_type) if not hasattr(s.object_type, "value") else s.object_type.value,
        "object_id": str(s.object_id),
        "role_id": str(s.role_id) if s.role_id else None,
        "role_name": s.role.name if s.role else "Все пользователи",
        "entries": [
            {"permission": e.permission if not hasattr(e.permission, "value") else e.permission.value,
             "state": e.state}
            for e in s.entries
        ],
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def create_snapshot(
    db: Session,
    is_super: bool,
    actor_user_id,
    object_type: str,
    object_id: str,
    role_id: str | None,
    entries: list[dict] | None = None,
    actor=None,
) -> dict:
    """Создание снапшота: копия набора прав шаблона (FR-100/105, US-044 шаг 1).

    role_id=None → снапшот виртуальной роли «Все пользователи» (FR-009).
    entries не заданы → копия состава шаблона роли в состоянии allow (US-044 шаг 1).
    """
    require_super(is_super)
    oid = _validate_object(db, object_type, object_id)
    parsed = _validate_entries(entries or [])

    role = None
    if role_id is not None:
        role = db.execute(
            select(models.Role).where(models.Role.id == parse_uuid(role_id))
        ).scalar_one_or_none()
        if role is None:
            raise not_found("Роль не найдена")
        if role.is_virtual_all_users:
            role = None  # виртуальная = NULL-снапшот

    snap = models.PermissionSnapshot(
        object_type=object_type,
        object_id=oid,
        role_id=role.id if role else None,
        created_by=parse_uuid(str(actor_user_id)),
    )
    initial: dict[str, str] = {}
    if role and not entries:
        # «Скопировать права из шаблона»: состав шаблона → allow (US-044 шаг 1)
        initial = {
            p.permission.value if hasattr(p.permission, "value") else str(p.permission): "allow"
            for p in role.permissions
        }
    for perm, state in initial.items():
        snap.entries.append(models.PermissionEntry(permission=models.PermissionCode(perm), state=state))
    for perm, state in parsed:
        # Явный список перекрывает/дополняет копию шаблона; unset не создаёт запись
        if state == "unset":
            initial.pop(perm, None)
            snap.entries = [e for e in snap.entries
                            if (e.permission.value if hasattr(e.permission, "value") else e.permission) != perm]
            continue
        existing = next((e for e in snap.entries
                         if (e.permission.value if hasattr(e.permission, "value") else e.permission) == perm), None)
        if existing:
            existing.state = state
        else:
            snap.entries.append(models.PermissionEntry(permission=models.PermissionCode(perm), state=state))
    db.add(snap)
    db.flush()
    # US-049 ш.1 (FR-140, LLD §11 snapshot.create): до commit_rights
    if actor is not None:
        audit_log(
            db, actor, "snapshot.create", "permission_snapshot", snap.id,
            details={"object_type": object_type, "object_id": str(oid),
                     "role_id": str(role.id) if role else None,
                     "entries": [{"permission": e.permission.value if hasattr(e.permission, "value") else str(e.permission),
                                  "state": e.state} for e in snap.entries]},
        )
    commit_rights(db)
    db.expire(snap, ["entries"])
    return _to_out(snap)


def update_snapshot(
    db: Session,
    is_super: bool,
    snapshot_id: str,
    entries: list[dict],
    actor=None,
) -> dict:
    """Правка состояний снапшота (US-044 шаг 2): allow/deny/unset."""
    require_super(is_super)
    snap = db.execute(
        select(models.PermissionSnapshot).where(models.PermissionSnapshot.id == parse_uuid(snapshot_id))
    ).scalar_one_or_none()
    if snap is None:
        raise not_found("Снапшот не найден")
    parsed = _validate_entries(entries)
    for perm, state in parsed:
        existing = next((e for e in snap.entries
                         if (e.permission.value if hasattr(e.permission, "value") else e.permission) == perm), None)
        if state == "unset":
            if existing:
                db.delete(existing)
        elif existing:
            existing.state = state
        else:
            snap.entries.append(models.PermissionEntry(permission=models.PermissionCode(perm), state=state))
    # US-049 ш.1 (FR-140, LLD §11 snapshot.update): до commit_rights
    if actor is not None:
        audit_log(
            db, actor, "snapshot.update", "permission_snapshot", snap.id,
            details={"entries": [{"permission": p, "state": s} for p, s in parsed]},
        )
    commit_rights(db)
    db.expire(snap, ["entries"])
    return _to_out(snap)


def delete_snapshot(db: Session, is_super: bool, snapshot_id: str, actor=None) -> None:
    require_super(is_super)
    snap = db.execute(
        select(models.PermissionSnapshot).where(models.PermissionSnapshot.id == parse_uuid(snapshot_id))
    ).scalar_one_or_none()
    if snap is None:
        raise not_found("Снапшот не найден")
    sid = snap.id
    db.delete(snap)
    # US-049 ш.1 (FR-140, LLD §11 snapshot.delete): до commit_rights
    if actor is not None:
        audit_log(db, actor, "snapshot.delete", "permission_snapshot", sid)
    commit_rights(db)
