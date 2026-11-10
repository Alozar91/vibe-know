# Notifications — транспорт (LLD §12.3, FR-134–140). Логика: use_cases/notifications/*.
#   GET  /notifications              — лента получателя (FR-137)
#   POST /notifications/{id}:read    — индивидуальное прочтение (FR-137)
#   POST /notifications:read-all     — отметить все свои (FR-137)
#   GET  /notification-triggers      — матрица триггеров (СА, US-047)
#   PUT  /notification-triggers/{et} — изменить триггер (СА, FR-140: аудит)
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases.errors import access_denied
from app.use_cases.notifications import triggers as trigger_uc
from app.use_cases.notifications.feed import (
    list_notifications,
    mark_all_read,
    mark_read,
    unread_count,
)

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
def list_notifications_ep(
    user: CurrentUserDep,
    unread_only: bool = False,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
) -> dict:
    """Лента уведомлений получателя (US-039 ш.3, FR-137)."""
    return list_notifications(db, user, unread_only=unread_only, page=page, per_page=per_page)


@router.get("/notifications:unread-count")
def unread_count_ep(user: CurrentUserDep, db: Session = Depends(get_db)) -> dict:
    """Счётчик непрочитанных для шапки UI (FR-137)."""
    return {"unread": unread_count(db, user)}


@router.post("/notifications/{notification_id}:read")
def mark_read_ep(
    notification_id: str, user: CurrentUserDep, db: Session = Depends(get_db)
) -> dict:
    """Отметить уведомление прочитанным (US-039 ш.3, FR-137)."""
    return mark_read(db, user, notification_id)


@router.post("/notifications:read-all")
def mark_all_read_ep(user: CurrentUserDep, db: Session = Depends(get_db)) -> dict:
    """Отметить все свои уведомления прочитанными (FR-137)."""
    return mark_all_read(db, user)


# --- Триггеры (СА; US-047, FR-134/135/140) ---

router_triggers = APIRouter(tags=["notifications"])


class TriggerIn(BaseModel):
    enabled: bool
    recipients: list[dict] = Field(default_factory=list)


def _require_super(is_super: bool) -> None:
    if not is_super:
        raise access_denied("Требуются права системного администратора")


@router_triggers.get("/notification-triggers")
def list_triggers_ep(
    user: CurrentUserDep, db: Session = Depends(get_db)
) -> list[dict]:
    """Матрица «триггер → типы получателей» (US-047 ш.1, FR-134/135)."""
    _require_super(user.is_super)
    return trigger_uc.list_triggers(db)


@router_triggers.put("/notification-triggers/{event_type}")
def update_trigger_ep(
    event_type: str,
    body: TriggerIn,
    user: CurrentUserDep,
    db: Session = Depends(get_db),
) -> dict:
    """Изменение триггера (US-047 ш.4–5, FR-140: аудит settings.change)."""
    _require_super(user.is_super)
    return trigger_uc.update_trigger(db, user.db_user, event_type, body.model_dump())
