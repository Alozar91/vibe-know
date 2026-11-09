# Этап 9: публикация событий уведомлений (LLD §8.1, FR-134).
#
# События публикуются В ТРАНЗАКЦИИ изменения материала (§4.1):
#   → in_review                        → material_sent_to_review
#   in_review → draft (возврат)        → material_rejected
#     (16.1-113: approved→draft события НЕ создаёт)
#   → archived (одиночная)             → material_archived
#   → archived (каскад, на каждого)    → child_auto_archived
#   правка контента в in_review        → material_changed_on_review
#   мастер изменён (критерий §2.5)     → master_changed (16.1-111: смена
#     ссылки/отвязка НЕ создают — событие об изменении МАСТЕР-материала)
# Прочие переходы — без специализированного события; если включён общий
# триггер status_changed, диспетчер создаёт уведомления и для них (FR-134:
# специализированные имеют приоритет — диспетчер отбрасывает status_changed
# для переходов, уже покрытых специализированным событием).
#
# file_blocked (FR-058) — прямое уведомление, минуя триггеры (§8.1) —
# создаётся конвейером файлов напрямую в notifications.
import json

from sqlalchemy.orm import Session

from app.db import models

# Событие → переходы, которые оно покрывает (для исключения дублей
# status_changed — FR-134; переход задаётся парой (from, to))
SPECIALIZED_TRANSITIONS: dict[str, set[tuple[str | None, str]]] = {
    "material_sent_to_review": {(None, "in_review")},  # любой from (кроме archived — запрещён)
    "material_rejected": {("in_review", "draft")},  # 16.1-113: только возвраты с ревью
    "material_archived": {(None, "archived")},  # одиночная архивация
    "child_auto_archived": {(None, "archived")},  # каскад — на подчинённого
}


def publish_event(
    db: Session,
    event_type: str,
    material_id,
    initiator_user_id=None,
    payload: dict | None = None,
) -> models.NotificationEvent:
    """Публикация события в транзакции вызывающего (без commit — §4.1)."""
    ev = models.NotificationEvent(
        event_type=event_type,
        material_id=material_id,
        initiator_user_id=initiator_user_id,
        payload=json.dumps(payload, ensure_ascii=False) if payload else None,
        processed=False,
    )
    db.add(ev)
    return ev


def specialized_event_for(from_status: str | None, to_status: str) -> str | None:
    """Специализированное событие для перехода (§8.1) или None.

    from_status=None означает «любой предыдущий» (матч по to_status).
    """
    for event_type, pairs in SPECIALIZED_TRANSITIONS.items():
        for f, t in pairs:
            if t == to_status and (f is None or f == from_status):
                return event_type
    # → in_review из любого статуса
    if to_status == "in_review":
        return "material_sent_to_review"
    # → archived одиночная: material_archived (каскад публикуется отдельно
    # для каждого подчинённого как child_auto_archived)
    if to_status == "archived":
        return "material_archived"
    return None
