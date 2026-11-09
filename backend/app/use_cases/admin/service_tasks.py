# Use-case: служебные задачи СА (LLD §2.2 service_tasks, FR-012, US-004 ш.4–5)
# и состояния фоновых задач (GET /tasks, NFR-014).
#
# GET /service-tasks            — открытые задачи (закрытые — ?all=true);
# POST /service-tasks/{id}:close — закрытие ТОЛЬКО при выполненном условии
# (transfer_review_right: право review уже назначено другому — US-004, US-044).
# GET /tasks                    — сводка system_tasks (antivirus/conversion/email).
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, not_found


def _validation_error(detail: str) -> DomainError:
    return DomainError(
        status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса", detail=detail
    )


def list_service_tasks(db: Session, is_super: bool, all: bool = False) -> list[dict]:
    """Служебный раздел СА (US-004 ш.4): открытые задачи передачи права."""
    require_super(is_super)
    stmt = select(models.ServiceTask).order_by(models.ServiceTask.created_at.desc())
    if not all:
        stmt = stmt.where(models.ServiceTask.closed_at.is_(None))
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": str(r.id),
            "task_type": r.task_type,
            "payload": r.payload or {},
            "state": r.state,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        }
        for r in rows
    ]


def _review_transferred(db: Session, task: models.ServiceTask) -> bool:
    """FR-012: право review в группе назначено другому пользователю (US-044)?

    Носители — как при создании задачи: роли с allow(review) в снапшотах
    цепочки группы; деактивированный пользователь носителем не считается.
    """
    from app.use_cases.permissions.eff import group_chain_ids

    p = task.payload or {}
    gid = parse_uuid(str(p.get("group_id", "")))
    uid = parse_uuid(str(p.get("user_id", "")))
    if gid is None:
        return False
    g = db.execute(select(models.Group).where(models.Group.id == gid)).scalar_one_or_none()
    if g is None or g.is_deleted:
        # Группа удалена — условие задачи снялось
        return True
    chain = group_chain_ids(db, g.path)

    rows = db.execute(
        select(models.PermissionSnapshot.role_id)
        .join(models.PermissionEntry,
              models.PermissionEntry.snapshot_id == models.PermissionSnapshot.id)
        .where(
            models.PermissionEntry.permission == "review",
            models.PermissionEntry.state == "allow",
            models.PermissionSnapshot.object_type == "group",
            models.PermissionSnapshot.object_id.in_(chain),
        )
    ).scalars().all()

    for ur in db.execute(select(models.UserRole)).scalars().all():
        if ur.role_id in rows and ur.user_id != uid:
            u = db.execute(select(models.User).where(models.User.id == ur.user_id)).scalar_one()
            if not u.is_deactivated:
                return True
    return False


def close_service_task(db: Session, actor: models.User, is_super: bool, task_id: str) -> dict:
    """Закрытие задачи (US-004 ш.5): только при выполненном условии (FR-012)."""
    require_super(is_super)
    tid = parse_uuid(task_id)
    if tid is None:
        raise _validation_error("Некорректный id задачи")
    t = db.execute(select(models.ServiceTask).where(models.ServiceTask.id == tid)).scalar_one_or_none()
    if t is None:
        raise not_found("Задача не найдена")
    if t.closed_at is not None:
        raise _validation_error("Задача уже закрыта")
    if t.task_type == "transfer_review_right":
        if not _review_transferred(db, t):
            raise DomainError(
                status=409, code="DOMAIN_RULE_VIOLATION", title="Условие не выполнено",
                detail="Право «Ревью (утверждение)» ещё не передано другому пользователю (FR-012, US-044)",
            )
    t.state = "done"
    t.closed_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "id": str(t.id), "task_type": t.task_type, "state": t.state,
        "closed_at": t.closed_at.isoformat(),
    }


def list_system_tasks(db: Session, is_super: bool, limit: int = 100) -> dict:
    """GET /tasks (NFR-014): состояния задач антивируса/конвертации/email + счётчики."""
    require_super(is_super)
    by_type_state = db.execute(
        select(
            models.SystemTask.task_type,
            models.SystemTask.state,
            func.count(models.SystemTask.id),
        ).group_by(models.SystemTask.task_type, models.SystemTask.state)
    ).all()
    summary = {}
    for task_type, state, cnt in by_type_state:
        summary.setdefault(task_type, {})[state] = cnt

    recent = db.execute(
        select(models.SystemTask)
        .order_by(models.SystemTask.scheduled_at.desc())
        .limit(limit)
    ).scalars().all()
    items = [
        {
            "id": str(r.id),
            "task_type": r.task_type,
            "object_type": r.object_type,
            "object_id": str(r.object_id) if r.object_id else None,
            "state": r.state,
            "attempts": r.attempts,
            "last_error": r.last_error,
            "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in recent
    ]
    return {"summary": summary, "items": items}
