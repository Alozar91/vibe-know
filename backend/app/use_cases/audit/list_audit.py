# Use-case: журнал аудита (LLD §11, FR-140–143, US-049) — только СА.
#
# Просмотр: пагинация + фильтры (action, object_type, actor, даты);
# записи неизменяемы (append-only); просмотр NOT FIXATED (FR-142: просмотры
# материалов не фиксируются; просмотр аудита — тоже не событие аудита).
# Выгрузка: NDJSON-поток (курсор по id); сама выгрузка фиксируется (FR-143).
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError


def list_audit(
    db: Session,
    is_super: bool,
    page: int = 1,
    per_page: int = 50,
    action: str | None = None,
    object_type: str | None = None,
    actor_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Журнал аудита (US-049 ш.1, FR-140): кто, когда, что, над чем."""
    require_super(is_super)
    q = db.execute(_filtered_query(action, object_type, actor_id, date_from, date_to))
    rows = q.scalars().all()
    total = len(rows)
    start = (page - 1) * per_page
    page_rows = rows[start:start + per_page]
    # Имена акторов одной выборкой (без N+1); системные события — NULL
    name_ids = {r.actor_user_id for r in page_rows if r.actor_user_id}
    actor_names = {}
    if name_ids:
        actor_names = dict(db.execute(
            select(models.User.id, models.User.display_name).where(
                models.User.id.in_(name_ids))
        ).all())
    return {
        "items": [_to_dict(r, actor_names) for r in page_rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


def _filtered_query(action, object_type, actor_id, date_from, date_to):
    from sqlalchemy import and_, true

    conds = [true()]
    if action:
        conds.append(models.AuditEntry.action == action)
    if object_type:
        conds.append(models.AuditEntry.object_type == object_type)
    if actor_id:
        aid = parse_uuid(actor_id)
        if aid is None:
            raise DomainError(
                status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                detail="Некорректный actor_id",
            )
        conds.append(models.AuditEntry.actor_user_id == aid)
    if date_from:
        try:
            conds.append(models.AuditEntry.occurred_at >= datetime.fromisoformat(date_from))
        except ValueError:
            raise DomainError(
                status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                detail="Некорректная дата date_from (ISO 8601)",
            )
    if date_to:
        try:
            conds.append(models.AuditEntry.occurred_at <= datetime.fromisoformat(date_to))
        except ValueError:
            raise DomainError(
                status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                detail="Некорректная дата date_to (ISO 8601)",
            )
    return select(models.AuditEntry).where(and_(*conds)).order_by(
        models.AuditEntry.id.desc()
    )


def _to_dict(r: models.AuditEntry, actor_names: dict | None = None) -> dict:
    return {
        "id": r.id,
        "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
        "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
        # US-049 ш.1 «кто»: отображаемое имя (пакетно; NULL — системные события)
        "actor_display_name": actor_names.get(r.actor_user_id) if actor_names else None,
        "actor_is_service": r.actor_is_service,
        "action": r.action,
        "object_type": r.object_type,
        "object_id": str(r.object_id) if r.object_id else None,
        "details": r.details or {},
    }


def iter_audit_ndjson(
    db: Session,
    actor,
    action=None,
    object_type=None,
    date_from=None,
    date_to=None,
):
    """Потоковая выгрузка NDJSON (FR-143): генератор строк по курсору.

    actor — principal (CurrentUser) или models.User: берём user_id/hasattr.
    Сама выгрузка фиксируется записью audit.export (US-049 ш.2) —
    коммит до генерации, чтобы выгрузка содержала собственную запись.
    """
    q = _filtered_query(action, object_type, None, date_from, date_to)
    # Порядок — по возрастанию id (хронология для комплаенса)
    q = q.order_by(models.AuditEntry.id.asc())
    rows = db.execute(q).scalars().all()
    # FR-143: фиксация выгрузки (до выдачи тела — запись попадает в файл)
    actor_id = getattr(actor, "user_id", None) or getattr(actor, "id", None)
    db.add(models.AuditEntry(
        actor_user_id=actor_id,
        actor_is_service=False,
        action="audit.export",
        object_type="audit",
        object_id=None,
        details={"format": "ndjson", "records": len(rows)},
    ))
    db.commit()
    for r in rows:
        yield json.dumps(_to_dict(r), ensure_ascii=False, default=str) + "\n"


def cleanup_expired(db: Session, retention_days: int) -> int:
    """Пакетное удаление по возрасту (FR-141); вызывается из worker."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    from sqlalchemy import delete

    res = db.execute(
        delete(models.AuditEntry).where(models.AuditEntry.occurred_at < cutoff)
    )
    db.commit()
    return res.rowcount
