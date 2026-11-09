# Use-case: деактивация учётной записи (FR-006, FR-011; US-004) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import get_user_or_404, require_super
from app.use_cases.errors import self_deactivation_forbidden
from app.use_cases.users.dto import UserOut, to_out
from app.use_cases.permissions.cache import commit_rights


def _sole_review_holder_groups(db: Session, user_id) -> list[models.Group]:
    """Группы, где деактивируемый — единственный носитель права review (FR-012).

    Носители права «Ревью (утверждение)» на группе — пользователи, чьи роли
    имеют allow(review) в снапшотах по цепочке «группа → предки» (§3.2:
    наследование по поддереву); без deny. Задача создаётся, если носитель
    этой группы — только деактивируемый (LLD §10).
    """
    from app.use_cases.permissions.eff import group_chain_ids

    groups = list(db.execute(
        select(models.Group).where(models.Group.is_deleted.is_(False))
    ).scalars().all())
    chains = {g.id: group_chain_ids(db, g.path) for g in groups}

    # Снапшоты групп с allow(review): роль → set(group_id, где действует)
    role_groups: dict = {}
    for snap in db.execute(
        select(models.PermissionSnapshot).where(
            models.PermissionSnapshot.object_type == "group",
        )
    ).scalars().all():
        if not any(
            (e.permission.value if hasattr(e.permission, "value") else str(e.permission)) == "review"
            and e.state == "allow"
            for e in snap.entries
        ):
            continue
        # Наследование вниз: снапшот на предке действует на всё поддерево
        for g in groups:
            if chains.get(g.id) and snap.object_id in chains[g.id]:
                role_groups.setdefault(snap.role_id, set()).add(g.id)

    # Носители по ролям (user_roles), включая деактивируемого — он ещё «был»
    holders: dict = {}  # group_id → set(user_id)
    for ur in db.execute(select(models.UserRole)).scalars().all():
        for gid in role_groups.get(ur.role_id, ()):
            holders.setdefault(gid, set()).add(ur.user_id)

    # Деактивируемый был носителем и других нет → задача передачи (LLD §10)
    return [
        g for g in groups
        if holders.get(g.id) == {user_id}
    ]


def _create_review_transfer_tasks(db: Session, u: models.User) -> int:
    """service_tasks(transfer_review_right) на каждую группу (US-004 ш.4, FR-012)."""
    groups = _sole_review_holder_groups(db, u.id)
    if not groups:
        return 0
    # Дедуп: не создавать повторно открытую задачу по той же группе/праву/пользователю
    open_tasks = db.execute(
        select(models.ServiceTask).where(
            models.ServiceTask.task_type == "transfer_review_right",
            models.ServiceTask.closed_at.is_(None),
        )
    ).scalars().all()
    seen = set()
    for t in open_tasks:
        p = t.payload or {}
        seen.add((str(p.get("group_id")), str(p.get("user_id"))))
    created = 0
    for g in groups:
        key = (str(g.id), str(u.id))
        if key in seen:
            continue
        db.add(models.ServiceTask(
            task_type="transfer_review_right",
            payload={
                "group_id": str(g.id),
                "group_name": g.name,
                "permission": "review",
                "user_id": str(u.id),
                "user_name": u.display_name,
            },
            state="queued",
        ))
        created += 1
    return created


def deactivate_user(
    db: Session, actor: models.User, is_super: bool, user_id: str
) -> UserOut:
    """Soft-деактивация; самодеактивация запрещена (деактивирует другой СА, US-004).

    Обратима активацией в Keycloak/сверкой (этап 10).
    """
    require_super(is_super)
    u = get_user_or_404(db, user_id)
    if u.id == actor.id:
        raise self_deactivation_forbidden()
    was_active = not u.is_deactivated
    u.is_deactivated = True
    if was_active:
        # FR-012/US-004 ш.4: единственный носитель review в группе →
        # незакрываемая служебная задача «Передать право ревью»
        _create_review_transfer_tasks(db, u)
    commit_rights(db)
    return to_out(u)
