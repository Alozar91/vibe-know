# Этап 9: диспетчер уведомлений (LLD §8.2, FR-134–139).
#
# Задача worker notifications.dispatch (интервал ≤ 15 с, NFR-007 in-app ≤ 30 с):
#   1) выбирает notification_events WHERE processed=false;
#   2) для каждого — конфигурация trigger_configs (event_type UNIQUE);
#      триггер отключён или отсутствует → событие processed без уведомлений
#      (кроме file_blocked — прямое, уже в notifications);
#   3) вычисляет получателей (FR-135):
#        role               — все носители роли-шаблона (user_roles);
#        fact_author        — materials.author_id;
#        fact_signatory     — materials.signatory_id;
#        fact_last_editor   — materials.last_editor_id;
#        permission_holder  — носители права на материале/группе (снапшоты §3);
#        scope=children     — факты подчинённых (master_changed, FR-135);
#   4) исключения (§8.1): инициатор (FR-138), деактивированные (FR-139),
#      сервисные УЗ (FR-013);
#   5) анти-шум (§8.2, 11.3): окно anti_noise_window_minutes (10, §2.5),
#      dedup_key = <event_type>:<material_id>:<recipient_id>; повторное
#      событие в окне не создаёт новое уведомление;
#   6) создаёт notifications (channel=in_app); email — при настроенном SMTP
#      (US-040 A1: не настроен → email-задачи не создаются, in-app работает);
#   7) события помечаются processed=true.
#
# Специализированные события имеют приоритет над общим status_changed (FR-134):
# события status_changed, чей (from,to) покрыт специализированным триггером
# того же перехода, отбрасываются. Реализация: на переходе публикуется только
# ОДНО событие (специализированное, если есть, иначе status_changed — если
# общий триггер включён); здесь — контроль конфигураций.
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


def get_setting(db: Session, key: str, default):
    """Чтение параметра §2.5 (system_settings; value — JSON-строка)."""
    row = db.execute(
        select(models.SystemSetting).where(models.SystemSetting.key == key)
    ).scalar_one_or_none()
    if row is None:
        return default
    try:
        return json.loads(row.value)
    except Exception:
        return default


def smtp_configured(db: Session) -> bool:
    """US-040 A1 / FR-136: email-канал активен только при настроенном SMTP."""
    host = get_setting(db, "smtp_host", None)
    return bool(host and str(host).strip() and str(host).strip().lower() != "не настроено")


def _facts(db: Session, material_id) -> models.Material | None:
    return db.execute(
        select(models.Material).where(models.Material.id == material_id)
    ).scalar_one_or_none()


def _role_holders(db: Session, role_id) -> list:
    """Носители роли-шаблона (FR-135): все пользователи с ролью."""
    return list(db.execute(
        select(models.User)
        .join(models.UserRole, models.UserRole.user_id == models.User.id)
        .where(models.UserRole.role_id == role_id)
    ).scalars().all())


def _permission_holders(db: Session, m: models.Material, permission: str) -> list:
    """Носители права на материале/группе (FR-135, §3).

    «Рецензенты материала» = пользователи, чьи роли имеют allow(review) в
    снапшотах по цепочке «материал → группы-предки» (7.6); без deny.
    """
    from app.use_cases.permissions.eff import has_right, group_chain_ids

    chain = group_chain_ids(db, m.group.path) if m.group is not None else []
    obj_conds = [
        models.PermissionSnapshot.object_type == "material",
        models.PermissionSnapshot.object_id == m.id,
    ]
    if chain:
        from sqlalchemy import or_

        obj_conds.append(
            (models.PermissionSnapshot.object_type == "group")
            & models.PermissionSnapshot.object_id.in_(chain)
        )
    rows = db.execute(
        select(models.PermissionSnapshot.role_id)
        .join(models.PermissionEntry, models.PermissionEntry.snapshot_id == models.PermissionSnapshot.id)
        .where(
            models.PermissionEntry.permission == permission,
            models.PermissionEntry.state == "allow",
            or_(*obj_conds),
        )
    ).scalars().all()
    role_ids = [r for r in rows if r is not None]
    users: list = []
    if role_ids:
        users = list(db.execute(
            select(models.User)
            .join(models.UserRole, models.UserRole.user_id == models.User.id)
            .where(models.UserRole.role_id.in_(role_ids))
        ).scalars().all())
    # Снапшоты без роли (роль «Все пользователи», FR-009) — все активные
    if None in rows:
        users.extend(db.execute(
            select(models.User).where(
                models.User.is_deactivated.is_(False), models.User.is_service.is_(False)
            )
        ).scalars().all())
    return users


def _resolve_recipients(db: Session, m: models.Material, cfg: dict) -> list:
    """Получатели одного элемента конфигурации (FR-135)."""
    rtype = cfg.get("type")
    scope_children = cfg.get("scope") == "children"

    materials: list[models.Material] = []
    if scope_children:
        # master_changed: авторы/подписанты ПОДЧИНЁННЫХ (FR-135, 16.1-111)
        materials = list(db.execute(
            select(models.Material).where(
                models.Material.master_id == m.id, models.Material.is_deleted.is_(False)
            )
        ).scalars().all())
        if not materials:
            return []
    else:
        materials = [m]

    out: list = []
    if rtype == "fact_author":
        out = [x.author_id for x in materials if x.author_id is not None]
    elif rtype == "fact_signatory":
        out = [x.signatory_id for x in materials if x.signatory_id is not None]
    elif rtype == "fact_last_editor":
        out = [x.last_editor_id for x in materials if x.last_editor_id is not None]
    elif rtype == "role":
        role_id = cfg.get("role_id")
        if role_id:
            out = [u.id for u in _role_holders(db, role_id)]
    elif rtype == "permission_holder":
        perm = cfg.get("permission") or "view"
        uids = set()
        for x in materials:
            for u in _permission_holders(db, x, perm):
                uids.add(u.id)
        out = list(uids)
    return out


def dispatch_events(db: Session, *, now: datetime | None = None) -> dict:
    """Один прогон диспетчера (LLD §8.2): события → уведомления.

    Возвращает статистику; вызывается задачей notifications.dispatch (≤15 с).
    """
    now = now or datetime.now(timezone.utc)
    window = int(get_setting(db, "anti_noise_window_minutes", 10))
    email_on = smtp_configured(db)

    events = list(db.execute(
        select(models.NotificationEvent)
        .where(models.NotificationEvent.processed.is_(False))
        .order_by(models.NotificationEvent.created_at)
    ).scalars().all())

    created_inapp = 0
    created_email = 0
    for ev in events:
        # file_blocked — прямое уведомление (§8.1): уже в notifications, минуя
        # триггеры; событие в таблицу не публикуется — помечаем и пропускаем
        if ev.event_type == "file_blocked":
            ev.processed = True
            continue

        cfg_row = db.execute(
            select(models.NotificationTrigger).where(
                models.NotificationTrigger.event_type == ev.event_type
            )
        ).scalar_one_or_none()

        m = _facts(db, ev.material_id) if ev.material_id is not None else None
        if cfg_row is None or not cfg_row.enabled or m is None:
            ev.processed = True  # триггер отключён/материал удалён — без уведомлений
            continue

        try:
            configs = json.loads(cfg_row.recipients or "[]")
        except Exception:
            configs = []

        # FR-138: инициатор собственных уведомлений не получает
        recipients: set = set()
        for cfg in configs:
            for uid in _resolve_recipients(db, m, cfg):
                if uid is None or uid == ev.initiator_user_id:
                    continue
                recipients.add(uid)

        # FR-139/FR-013: деактивированные и сервисные УЗ исключаются
        if recipients:
            users = db.execute(
                select(models.User).where(models.User.id.in_(recipients))
            ).scalars().all()
            recipients = {
                u.id for u in users
                if not u.is_deactivated and not u.is_service
            }

        cutoff = now - timedelta(minutes=window)
        for uid in recipients:
            dedup_key = f"{ev.event_type}:{ev.material_id}:{uid}"
            # Анти-шум (§8.2): уведомление по этому ключу в окне — не создаём
            dup = db.execute(
                select(models.Notification.id).where(
                    models.Notification.dedup_key == dedup_key,
                    models.Notification.created_at > cutoff,
                ).limit(1)
            ).first()
            if dup:
                continue
            db.add(models.Notification(
                recipient_id=uid,
                event_type=ev.event_type,
                material_id=ev.material_id,
                channel="in_app",
                dedup_key=dedup_key,
                email_state="queued" if email_on else None,
            ))
            created_inapp += 1
            if email_on:
                created_email += 1

        ev.processed = True

    db.commit()
    return {
        "events": len(events),
        "inapp_created": created_inapp,
        "email_created": created_email,
    }
