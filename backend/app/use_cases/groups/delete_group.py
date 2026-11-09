# Use-case: удаление группы (FR-018–022, US-052 шаги 4–7) — только СА.
# Пустая группа (без подгрупп и материалов, включая удалённые) — физический DELETE (FR-018);
# непустая ветка — soft-delete всей ветки (FR-019); мастер с подчинёнными вне ветки — запрет (FR-020).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import get_group_or_404, require_super
from app.use_cases.errors import DomainError, domain_rule_violation, not_found
from app.use_cases.groups.dto import to_out
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.permissions.cache import commit_rights


def delete_group(
    db: Session, is_super: bool, group_id: str, confirm_rights: bool = False, actor=None
) -> dict:
    """Решение физ/soft — система; предупреждение о правах — без confirm_rights → 409.

    Возвращает {'mode': 'hard'|'soft', 'subtree_count': N}.
    """
    require_super(is_super)
    g = get_group_or_404(db, group_id)
    subtree = _subtree(db, g)

    # FR-020: в ветке мастер с неудалёнными подчинёнными вне ветки (материалы — этап 4;
    # здесь проверка групповой части: подгруппы не блокируют soft, но блокируют hard)
    _check_master_lock(db, subtree)

    # FR-018: пустая = «без подгрупп и материалов, включая удалённые» —
    # фильтр is_deleted не ставим
    has_children = db.execute(
        select(models.Group.id).where(models.Group.parent_id == g.id).limit(1)
    ).first() is not None
    has_materials = _has_materials(db, subtree)  # этап 4: всегда False до появления materials

    if not has_children and not has_materials:
        # Физическое удаление; предупреждение о назначенных правах (US-052 шаг 4)
        if not confirm_rights and _has_snapshots(db, subtree):
            raise DomainError(
                status=409, code="RIGHTS_CONFIRM_REQUIRED", title="Требуется подтверждение",
                detail="На группу назначены права; подтвердите их удаление (confirm_rights=true)",
                params={"has_rights": True},
            )
        _delete_snapshots(db, subtree)
        db.delete(g)
        # US-049 ш.1 (FR-140, LLD §11 group.delete): до commit_rights
        if actor is not None:
            audit_log(db, actor, "group.delete", "group", g.id,
                      details={"mode": "hard", "name": g.name})
        commit_rights(db)
        return {"mode": "hard", "subtree_count": 1}

    # Soft-delete ветки (FR-019): подгруппы и материалы скрываются
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    for node in subtree:
        node.is_deleted = True
        node.deleted_at = now
    # US-049 ш.1 (FR-140, LLD §11 group.delete)
    if actor is not None:
        audit_log(db, actor, "group.delete", "group", g.id,
                  details={"mode": "soft", "name": g.name, "subtree_count": len(subtree)})
    commit_rights(db)
    return {"mode": "soft", "subtree_count": len(subtree)}


def restore_group(db: Session, is_super: bool, group_id: str) -> dict:
    """Восстановление ветки (US-050; удалённые — только СА)."""
    require_super(is_super)
    g = db.execute(
        select(models.Group).where(models.Group.id == _uuid(group_id))
    ).scalar_one_or_none()
    if g is None or not g.is_deleted:
        raise not_found("Удалённая группа не найдена")
    # Восстановление ветки: все узлы path-поддерева
    for node in _subtree(db, g, only_deleted=True):
        node.is_deleted = False
        node.deleted_at = None
    commit_rights(db)
    return to_out(g)


def _uuid(value: str):
    from app.use_cases.common import parse_uuid

    return parse_uuid(value)


def _subtree(db: Session, root: models.Group, only_deleted: bool = False) -> list[models.Group]:
    """Поддерево по path-префиксу (LLD §3.2: prefix-поиск поддерева)."""
    stmt = select(models.Group).where(models.Group.path.like(f"{root.path}%"))
    if only_deleted:
        stmt = stmt.where(models.Group.is_deleted.is_(True))
    return list(db.execute(stmt).scalars().all())


def _has_materials(db: Session, subtree: list[models.Group]) -> bool:
    """materials в ветке (этап 4: таблицы materials ещё нет → False)."""
    if not hasattr(models, "Material"):
        return False
    ids = [g.id for g in subtree]
    return db.execute(
        select(models.Material.id).where(models.Material.group_id.in_(ids)).limit(1)
    ).first() is not None


def _check_master_lock(db: Session, subtree: list[models.Group]) -> None:
    """FR-020: мастер с неудалёнными подчинёнными вне ветки (этап 4)."""
    if not hasattr(models, "Material"):
        return
    ids = [g.id for g in subtree]
    masters = db.execute(
        select(models.Material).where(
            models.Material.group_id.in_(ids),
            models.Material.master_id.is_not(None),
            models.Material.is_deleted.is_(False),
        )
    ).scalars().all()
    inside = {m.id for m in masters}
    for m in masters:
        child = db.execute(
            select(models.Material.id).where(
                models.Material.master_id == m.id, models.Material.id.not_in(inside),
                models.Material.is_deleted.is_(False),
            ).limit(1)
        ).first()
        if child:
            raise domain_rule_violation(
                409, "Ветка содержит мастер-материал с подчинёнными вне ветки"
            )


def _has_snapshots(db: Session, subtree: list[models.Group]) -> bool:
    if not hasattr(models, "PermissionSnapshot"):
        return False
    ids = [g.id for g in subtree]
    return db.execute(
        select(models.PermissionSnapshot.id).where(
            models.PermissionSnapshot.object_type == "group",
            models.PermissionSnapshot.object_id.in_(ids),
        ).limit(1)
    ).first() is not None


def _delete_snapshots(db: Session, subtree: list[models.Group]) -> None:
    if not hasattr(models, "PermissionSnapshot"):
        return
    ids = [g.id for g in subtree]
    for snap in db.execute(
        select(models.PermissionSnapshot).where(
            models.PermissionSnapshot.object_type == "group",
            models.PermissionSnapshot.object_id.in_(ids),
        )
    ).scalars().all():
        db.delete(snap)
