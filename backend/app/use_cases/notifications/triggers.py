# Use-case: конфигурация триггеров уведомлений (LLD §12.3, US-047, FR-134/135/140).
#
# GET  — любым СА (просмотр матрицы «триггер → типы получателей»);
# PUT  — СА, изменение фиксируется в аудите (FR-140, action settings.change).
# Состав конфигурации валидируется: event_type — из реестра §2.1;
# recipients — массив {type, role_id?, permission?, scope?}.
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.errors import DomainError, not_found
from app.use_cases.lifecycle.audit import audit_log


def _validation_error(detail: str) -> DomainError:
    return DomainError(
        status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса", detail=detail
    )

# Реестр событий §2.1 (для валидации PUT; file_blocked — вне триггеров, §8.1)
TRIGGERABLE_EVENTS = {
    "material_sent_to_review",
    "material_rejected",
    "material_archived",
    "child_auto_archived",
    "master_changed",
    "material_changed_on_review",
    "status_changed",
}

RECIPIENT_TYPES = {
    "role",
    "fact_author",
    "fact_signatory",
    "fact_last_editor",
    "permission_holder",
}


def _validate_recipients(db: Session, recipients: list) -> list[dict]:
    if not isinstance(recipients, list):
        raise _validation_error("recipients должен быть массивом")
    out: list[dict] = []
    for r in recipients:
        if not isinstance(r, dict) or r.get("type") not in RECIPIENT_TYPES:
            raise _validation_error("Некорректный type получателя (FR-135)")
        entry = {"type": r["type"]}
        if r["type"] == "role":
            role_id = r.get("role_id")
            if not role_id:
                raise _validation_error("Для type=role обязателен role_id")
            role = db.execute(
                select(models.Role).where(models.Role.id == parse_role_id(role_id))
            ).scalar_one_or_none()
            if role is None:
                raise not_found("Роль не найдена")
            entry["role_id"] = str(role.id)
        if r["type"] == "permission_holder":
            perm = r.get("permission")
            if not perm:
                raise _validation_error("Для type=permission_holder обязателен permission")
            entry["permission"] = str(perm)
        scope = r.get("scope")
        if scope is not None:
            if scope != "children":
                raise _validation_error("Допустимый scope — только 'children' (FR-135)")
            entry["scope"] = "children"
        out.append(entry)
    return out


def parse_role_id(v: str):
    from app.use_cases.common import parse_uuid

    return parse_uuid(v)


def list_triggers(db: Session) -> list[dict]:
    """Матрица «триггер → типы получателей» (US-047 ш.1)."""
    rows = db.execute(
        select(models.NotificationTrigger).order_by(models.NotificationTrigger.event_type)
    ).scalars().all()
    return [
        {
            "event_type": r.event_type,
            "enabled": r.enabled,
            "recipients": json.loads(r.recipients or "[]"),
        }
        for r in rows
    ]


def update_trigger(db: Session, actor: models.User, event_type: str, body: dict) -> dict:
    """Обновление одного триггера (US-047 ш.4, FR-140: аудит изменений)."""
    if event_type not in TRIGGERABLE_EVENTS:
        raise not_found("Неизвестный event_type")

    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise _validation_error("enabled должен быть boolean")
    recipients = _validate_recipients(db, body.get("recipients", []))

    row = db.execute(
        select(models.NotificationTrigger).where(
            models.NotificationTrigger.event_type == event_type
        )
    ).scalar_one_or_none()
    if row is None:
        # Конфигурация для валидного event_type отсутствует (не сидирована) —
        # создаём (LLD: одна строка на событие, UNIQUE).
        row = models.NotificationTrigger(
            event_type=event_type,
            enabled=enabled,
            recipients=json.dumps(recipients, ensure_ascii=False),
        )
        db.add(row)
    else:
        row.enabled = enabled
        row.recipients = json.dumps(recipients, ensure_ascii=False)

    # FR-140: аудит административной операции (US-047 ш.5); object_id — UUID
    # колонка, event_type фиксируется в details
    audit_log(
        db, actor, "settings.change", "notification_trigger", None,
        details={"event_type": event_type, "enabled": enabled, "recipients": recipients},
    )
    db.commit()
    return {
        "event_type": event_type,
        "enabled": enabled,
        "recipients": recipients,
    }
