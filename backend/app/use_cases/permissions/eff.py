# SQL-предикат прав (LLD §3.2, FR-099–109; US-045): сборка eff-правил.
#
# Семантика §3.2: правила всех ролей пользователя (включая виртуальную «Все
# пользователи», FR-009) собираются по цепочке «материал → группа → … →
# корень» (path-префикс, FR-101); deny побеждает (FR-102); отсутствие правил —
# запрет; СА — в обход (FR-104). Ветки видимости (FR-066):
#   draft/in_review/approved — автор или носители edit/delete/review/publish/archive;
#   published/archived       — носители view.
# Реализация SQLAlchemy Core: bool_or ≡ max(case), группировка по permission.
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.permissions.cache import get_cached, put_cached

PROCESS_PERMS = ("edit", "delete", "review", "publish", "archive")
DRAFT_STATUSES = ("draft", "in_review", "approved")
PUBLIC_STATUSES = ("published", "archived")
PERMISSIONS_CATALOG = [p.value for p in models.PermissionCode]  # FR-106


def user_role_ids(db: Session, user_id) -> list:
    """ID ролей пользователя + None, если существует виртуальная «Все пользователи».

    memberships кэшируются (§3.3); инвалидация — NOTIFY после мутаций ролей.
    """
    key = f"uroles:{user_id}"
    cached = get_cached(key)
    if cached is not None:
        return cached
    ids = list(
        db.execute(
            select(models.UserRole.role_id).where(models.UserRole.user_id == user_id)
        ).scalars()
    )
    has_virtual = db.execute(
        select(models.Role.id).where(models.Role.is_virtual_all_users).limit(1)
    ).first() is not None
    if has_virtual:
        ids.append(None)
    put_cached(key, ids)
    return ids


def eff_rows(
    db: Session, user_id, chain_group_ids, material_id=None
) -> dict[str, tuple[int, int]]:
    """{permission: (has_allow, has_deny)} по объектам цепочки (материал + группы).

    Эквивалент eff-CTE §3.2; отсутствие записи = «не задано» (8.3).
    """
    role_ids = user_role_ids(db, user_id)
    obj_conds = []
    if material_id is not None:
        obj_conds.append(
            and_(
                models.PermissionSnapshot.object_type == "material",
                models.PermissionSnapshot.object_id == material_id,
            )
        )
    if chain_group_ids:
        obj_conds.append(
            and_(
                models.PermissionSnapshot.object_type == "group",
                models.PermissionSnapshot.object_id.in_(chain_group_ids),
            )
        )
    if not obj_conds:
        return {}
    conds = [
        or_(
            models.PermissionSnapshot.role_id.in_(role_ids) if role_ids else false_cond(),
            models.PermissionSnapshot.role_id.is_(None),
        )
        if role_ids
        else models.PermissionSnapshot.role_id.is_(None),
        or_(*obj_conds),
    ]
    # Кэш снапшотов (§3.3): ключ = цепочка объектов + роли пользователя.
    # Инвалидация — NOTIFY rights_invalidate после commit мутаций прав/ролей.
    chain_key = ",".join(
        ([str(material_id)] if material_id else []) + [str(g) for g in chain_group_ids]
    ) or "none"
    cache_key = f"eff:{user_id}:{chain_key}"
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    rows = db.execute(
        select(
            models.PermissionEntry.permission,
            func.max(case((models.PermissionEntry.state == "allow", 1), else_=0)),
            func.max(case((models.PermissionEntry.state == "deny", 1), else_=0)),
        )
        .select_from(models.PermissionSnapshot)
        .join(
            models.PermissionEntry,
            models.PermissionEntry.snapshot_id == models.PermissionSnapshot.id,
        )
        .where(and_(*conds))
        .group_by(models.PermissionEntry.permission)
    ).all()
    result = {perm: (int(a), int(d)) for perm, a, d in rows}
    put_cached(cache_key, result)
    return result


def false_cond():
    """Конъюнкция, всегда ложная (для пустых цепочек)."""
    return models.PermissionSnapshot.object_id.is_not(None)


def has_right(eff: dict[str, tuple[int, int]], permission: str) -> bool:
    """has_right(eff, p) §3.2: has_allow и не has_deny; нет записи — «не задано»."""
    a, d = eff.get(permission, (0, 0))
    return a == 1 and d == 0


def group_chain_ids(db: Session, group_path: str | None) -> list:
    """Цепочка «группа → … → корень»: path-префиксы (FR-101), не удалённые."""
    if not group_path:
        return []
    return list(
        db.execute(
            select(models.Group.id).where(
                models.Group.is_deleted.is_(False),
                # material → группа → …: path группы-предка — префикс path группы материала
                sa_literal(group_path).like(models.Group.path.concat("%")),
            )
        ).scalars()
    )


def sa_literal(v: str):
    from sqlalchemy import literal

    return literal(v)
