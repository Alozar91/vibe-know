# Use-cases ленты уведомлений (LLD §12.3, FR-137): получатель видит только свои.
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid
from app.use_cases.errors import not_found


def _user_id(user) -> object:
    # user — CurrentUser (user_id) или models.User (id) в тестах
    return getattr(user, "user_id", None) or getattr(user, "id", None)


def list_notifications(
    db: Session, user, *, unread_only: bool = False, page: int = 1, per_page: int = 50,
) -> dict:
    """Лента уведомлений (FR-137): только свои, новые → старые."""
    uid = _user_id(user)
    page = max(1, int(page or 1))
    per_page = min(200, max(1, int(per_page or 50)))
    stmt = select(models.Notification).where(models.Notification.recipient_id == uid)
    if unread_only:
        stmt = stmt.where(models.Notification.read_at.is_(None))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(desc(models.Notification.created_at))
        .offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()
    unread = db.execute(
        select(func.count()).select_from(models.Notification).where(
            models.Notification.recipient_id == uid,
            models.Notification.read_at.is_(None),
        )
    ).scalar_one()
    return {
        "items": [_to_out(n) for n in rows],
        "total": total,
        "unread": unread,
        "page": page,
        "per_page": per_page,
    }


def unread_count(db: Session, user) -> int:
    """Счётчик непрочитанных (FR-137, NFR-007 — опрос шапкой)."""
    return db.execute(
        select(func.count()).select_from(models.Notification).where(
            models.Notification.recipient_id == _user_id(user),
            models.Notification.read_at.is_(None),
        )
    ).scalar_one()


def mark_read(db: Session, user, notification_id: str) -> dict:
    """Индивидуальное прочтение (FR-137): только своё уведомление."""
    from datetime import datetime, timezone

    n = db.execute(
        select(models.Notification).where(
            models.Notification.id == parse_uuid(notification_id)
        )
    ).scalar_one_or_none()
    if n is None or n.recipient_id != _user_id(user):
        raise not_found("Уведомление не найдено")
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        db.commit()
    return _to_out(n)


def mark_all_read(db: Session, user) -> dict:
    """Отметить все свои непрочитанные (FR-137, POST /notifications:read-all)."""
    from datetime import datetime, timezone

    uid = _user_id(user)
    rows = db.execute(
        select(models.Notification).where(
            models.Notification.recipient_id == uid,
            models.Notification.read_at.is_(None),
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for n in rows:
        n.read_at = now
    db.commit()
    return {"marked": len(rows)}


def _to_out(n: models.Notification) -> dict:
    return {
        "id": str(n.id),
        "event_type": n.event_type,
        "material_id": str(n.material_id) if n.material_id else None,
        "dedup_key": n.dedup_key,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }
