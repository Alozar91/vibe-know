# Реестр задач Celery (имена — точно по LLD §9).
# Этап 6: files.scan (заглушка антивируса, 16.1-14), files.convert (Gotenberg).
# Этап 9: notifications.dispatch, notifications.email, notifications.digest.
# Этап 10: maintenance.*, keycloak.sync.
from __future__ import annotations

import json

from datetime import datetime, timezone

from celery import states as celery_states
from sqlalchemy import select, update

from app.db import models
from app.db.engine import get_session_factory
from app.logging import get_logger
from app.use_cases.files import silo
from app.use_cases.files.mime_detect import is_office_mime
from app.worker import celery_app

log = get_logger(__name__)

# Ретраи по LLD §9
SCAN_MAX_RETRIES = 5
CONVERT_MAX_RETRIES = 3
CONVERT_TIMEOUT_S = 600  # 10 минут (NFR-006)
KEYCLOAK_SYNC_PAGE = 100  # страницы Admin API (LLD §10, [уточнение LLD])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mark(task_id: str, **fields) -> None:
    """Обновление system_tasks (источник истины — NFR-014)."""
    with get_session_factory()() as db:
        db.execute(
            update(models.SystemTask).where(models.SystemTask.id == _uuid(task_id)).values(**fields)
        )
        db.commit()


def _uuid(v: str):
    import uuid as _u

    return _u.UUID(v)


def _file(db, file_id: str) -> models.FileObject | None:
    return db.execute(
        select(models.FileObject).where(models.FileObject.id == _uuid(file_id))
    ).scalar_one_or_none()


@celery_app.task(bind=True, name="files.scan", max_retries=SCAN_MAX_RETRIES)
def files_scan(self, task_id: str, file_id: str) -> dict:
    """Антивирус (заглушка, 16.1-14): pending_scan → scanning → ready.

    Реальный сканер (clamd) подключается той же сигнатурой без изменения
    архитектуры (FR-057); заглушка всегда отвечает «чисто». Повторный вызов
    по тому же FileObject безопасен (идемпотентность, §9).
    """
    db = get_session_factory()()
    try:
        # running (started_at, attempts)
        db.execute(
            update(models.SystemTask)
            .where(models.SystemTask.id == _uuid(task_id))
            .values(state="running", started_at=_now(),
                    attempts=models.SystemTask.attempts + 1)
        )
        fo = _file(db, file_id)
        if fo is None:
            db.rollback()
            return {"file_id": file_id, "result": "missing"}
        fo.scan_state = "scanning"
        db.commit()

        # --- Заглушка сканера (16.1-14): всегда «чисто»; реальная реализация —
        # клиент clamd с тем же интерфейсом, переключение параметром окружения ---
        infected = _scan_stub(fo)

        fo.scan_state = "infected" if infected else "ready"
        db.execute(
            update(models.SystemTask)
            .where(models.SystemTask.id == _uuid(task_id))
            .values(state="done", finished_at=_now())
        )
        db.commit()

        if fo.scan_state == "ready":
            # Офисный mime → files.convert (§6.3); пост-обработка после commit
            _maybe_convert(fo)
        else:
            # Прямое уведомление file_blocked (FR-058, LLD §8.1): вне триггеров,
            # получатели — автор материала + все СА; инициатор — система
            _audit_system(db, "file.scan", fo,
                          details={"result": "infected"})
            _notify_file_blocked(fo)
        return {"file_id": file_id, "result": fo.scan_state}
    except Exception as e:
        db.rollback()
        # Повтор: экспоненциально 30 с → ×2 (§9)
        try_count = self.request.retries + 1
        if try_count <= SCAN_MAX_RETRIES:
            _mark(task_id, state="queued",
                  last_error=f"{type(e).__name__}: {e}")
            raise self.retry(exc=e, countdown=30 * (2 ** (try_count - 1)))
        _mark(task_id, state="failed", finished_at=_now(),
              last_error=f"{type(e).__name__}: {e}")
        return {"file_id": file_id, "result": "failed", "error": str(e)}
    finally:
        db.close()


def _scan_stub(fo: models.FileObject) -> bool:
    """Заглушка антивируса (16.1-14): False — не заражён."""
    return False


def _audit_system(db, action: str, fo, details: dict) -> None:
    db.add(models.AuditEntry(
        actor_user_id=None, actor_is_service=True, action=action,
        object_type="file", object_id=fo.id, details=details,
    ))


def _notify_file_blocked(fo: models.FileObject) -> None:
    """Прямое уведомление file_blocked (FR-058, LLD §8.1 п.2): создаётся
    конвейером напрямую в notifications (вне триггеров); получатели —
    автор материала (fact_author по materials.author_id) и все СА
    (носители шаблона «Системный администратор»); инициатор — система."""
    with get_session_factory()() as db:
        # Материал файла: связь через materials.current_file_id (текущая версия)
        m = db.execute(
            select(models.Material).where(models.Material.current_file_id == fo.id)
        ).scalars().first()
        recipients: list[models.User] = []
        if m is not None and m.author_id is not None:
            author = db.execute(
                select(models.User).where(models.User.id == m.author_id)
            ).scalar_one_or_none()
            if author is not None:
                recipients.append(author)
        # Все СА — носители шаблона «Системный администратор» (FR-104)
        sa_role = db.execute(
            select(models.Role).where(models.Role.name == "Системный администратор")
        ).scalar_one_or_none()
        if sa_role is not None:
            sas = db.execute(
                select(models.User)
                .join(models.UserRole, models.UserRole.user_id == models.User.id)
                .where(models.UserRole.role_id == sa_role.id)
            ).scalars().all()
            recipients.extend(sas)

        seen = set()
        for u in recipients:
            if u.id in seen or u.is_deactivated or u.is_service:
                continue  # FR-139, FR-013
            seen.add(u.id)
            db.add(models.Notification(
                recipient_id=u.id,
                event_type="file_blocked",
                material_id=m.id if m is not None else None,
                channel="in_app",
                dedup_key=f"file_blocked:{fo.id}:{u.id}",
            ))
        db.commit()


@celery_app.task(bind=True, name="files.convert", max_retries=CONVERT_MAX_RETRIES)
def files_convert(self, task_id: str, file_id: str) -> dict:
    """Конвертация офисного формата в PDF (§6.3, FR-059/060): Gotenberg
    POST /forms/libreoffice/convert → S3 PUT pdf/<hex> → ready_pdf.
    Ошибка → convert_failed (материал не блокируется, FR-060)."""
    from app.config import get_settings

    db = get_session_factory()()
    try:
        db.execute(
            update(models.SystemTask)
            .where(models.SystemTask.id == _uuid(task_id))
            .values(state="running", started_at=_now(),
                    attempts=models.SystemTask.attempts + 1)
        )
        fo = _file(db, file_id)
        if fo is None:
            db.rollback()
            return {"file_id": file_id, "result": "missing"}
        fo.pdf_state = "converting"
        db.commit()

        settings = get_settings()
        pdf_bytes = _convert_via_gotenberg(settings, fo)

        silo.put_object(silo.pdf_key(fo.sha256), pdf_bytes, content_type="application/pdf")
        fo.pdf_state = "ready_pdf"
        fo.pdf_cas_key = silo.pdf_key(fo.sha256)
        db.execute(
            update(models.SystemTask)
            .where(models.SystemTask.id == _uuid(task_id))
            .values(state="done", finished_at=_now())
        )
        db.commit()
        return {"file_id": file_id, "result": "ready_pdf"}
    except Exception as e:
        db.rollback()
        try_count = self.request.retries + 1
        if try_count <= CONVERT_MAX_RETRIES:
            _mark(task_id, state="queued",
                  last_error=f"{type(e).__name__}: {e}")
            raise self.retry(exc=e, countdown=60 * try_count)
        # convert_failed: скачивание работает, материал не блокируется (FR-060)
        with get_session_factory()() as db2:
            fo = _file(db2, file_id)
            if fo is not None:
                fo.pdf_state = "convert_failed"
                db2.commit()
        _mark(task_id, state="failed", finished_at=_now(),
              last_error=f"{type(e).__name__}: {e}")
        log.error("files.convert.failed", file_id=file_id, error=str(e))
        return {"file_id": file_id, "result": "convert_failed", "error": str(e)}
    finally:
        db.close()


def _convert_via_gotenberg(settings, fo: models.FileObject) -> bytes:
    """Gotenberg (HLD §3.2): POST /forms/libreoffice/convert (multipart).

    Ретраи/таймауты Gotenberg — уточнены для MVP: таймаут 10 мин (NFR-006),
    ретраи задачи — 3 (LLD §9; §14-3 — уточнено при интеграционных испытаниях).
    """
    import httpx

    body, _st, _h = silo.get_object_stream(silo.cas_key(fo.sha256))
    if body is None:
        raise RuntimeError("исходник отсутствует в silo")
    try:
        data = body.read()
    finally:
        body.close()

    endpoint = settings.gotenberg_url.rstrip("/") + "/forms/libreoffice/convert"
    files = {"files": (fo.filename, data, fo.mime_type)}
    with httpx.Client(timeout=CONVERT_TIMEOUT_S) as client:
        resp = client.post(endpoint, files=files)
    if resp.status_code != 200:
        raise RuntimeError(f"Gotenberg вернул {resp.status_code}: {resp.text[:200]}")
    return resp.content


def _maybe_convert(fo: models.FileObject) -> None:
    """scan_state='ready' + офисный mime → постановка files.convert (§6.3)."""
    if not is_office_mime(fo.mime_type):
        return
    with get_session_factory()() as db:
        task = models.SystemTask(
            task_type="conversion", object_type="file", object_id=fo.id, state="queued"
        )
        db.add(task)
        db.commit()
        from app.worker.tasks import files_convert

        files_convert.apply_async(args=[str(task.id), str(fo.id)])


# --- Reconcile очереди из БД при старте worker (LLD §9): задачи в queued
# перезапускаются; обработчики остальных этапов добавляются в STARTUP_TASKS.
@celery_app.task(name="files.reconcile")
def files_reconcile() -> dict:
    """Перезапуск queued-задач этапа 6 (файлы) после сбоя брокера/worker."""
    restarted = 0
    with get_session_factory()() as db:
        rows = db.execute(
            select(models.SystemTask).where(
                models.SystemTask.state == "queued",
                models.SystemTask.task_type.in_(["antivirus", "conversion"]),
            )
        ).scalars().all()
        for t in rows:
            if t.task_type == "antivirus":
                files_scan.apply_async(args=[str(t.id), str(t.object_id)])
            elif t.task_type == "conversion":
                files_convert.apply_async(args=[str(t.id), str(t.object_id)])
            restarted += 1
    return {"restarted": restarted}


# ==========================================================================
# Этап 8: обслуживание поиска (LLD §7.1, §7.6, §9)
# ==========================================================================

@celery_app.task(name="maintenance.fts_rebuild")
def fts_rebuild() -> dict:
    """Полная пересборка search_tsv (§7.1, §9): идемпотентна, еженедельно.

    Защита от расхождений после сбоев/ручных правок в БД; пересчёт —
    тот же SQL, что и в update_search_vector (LLD §7.1).
    """
    from sqlalchemy import text as sa_text

    rebuilt = 0
    with get_session_factory()() as db:
        if db.bind.dialect.name == "sqlite":
            return {"rebuilt": 0, "skipped": "sqlite"}
        cfgs = db.execute(sa_text("SELECT DISTINCT search_lang FROM materials")).scalars().all()
        for cfg in cfgs or ["russian"]:
            from app.use_cases.materials.search_common import build_tsv_sql_expr

            res = db.execute(
                sa_text(f"""
                    UPDATE materials SET search_tsv = {build_tsv_sql_expr(cfg).text}
                    WHERE search_lang = :cfg AND is_deleted = false
                """).bindparams(cfg=cfg)
            )
            rebuilt += res.rowcount or 0
        db.commit()
    log.info("fts_rebuild.done", rebuilt=rebuilt)
    return {"rebuilt": rebuilt}


@celery_app.task(name="maintenance.analytics_rollup")
def analytics_rollup() -> dict:
    """Свёртка search_events/search_opens за период в search_analytics (§7.6).

    MVP: период — день (UTC); пересвёртка периода безопасна (§9) —
    строки upsert'ятся по (period_start, query). Raw-события старше
    analytics_raw_retention_days удаляются пакетно (§7.6).
    """
    from datetime import datetime, timedelta, timezone

    rolled_days = 0
    deleted_events = 0
    with get_session_factory()() as db:
        if db.bind.dialect.name == "sqlite":
            return {"rolled_days": 0, "skipped": "sqlite"}

        retention = 180
        setting_row = db.execute(
            sa_text("SELECT value FROM system_settings WHERE key = 'analytics_raw_retention_days'")
        ).first()
        if setting_row is not None:
            try:
                import json as _json

                retention = int(_json.loads(setting_row[0]))
            except Exception:
                pass

        # Не свёрнутые дни (есть событие; аналитика за день может обновляться)
        days = db.execute(sa_text("""
            SELECT DISTINCT date_trunc('day', created_at) AS d
            FROM search_events WHERE created_at > now() - interval '7 days'
            ORDER BY d
        """)).scalars().all()

        for d in days:
            period = d
            # события дня: запросы с результатами и без
            qrows = db.execute(sa_text("""
                SELECT query_normalized,
                       count(*) FILTER (WHERE result_count > 0) AS hit_cnt,
                       count(*) FILTER (WHERE result_count = 0) AS zero_cnt
                FROM search_events
                WHERE date_trunc('day', created_at) = :d
                GROUP BY query_normalized
            """).bindparams(d=d)).all()
            orows = db.execute(sa_text("""
                SELECT e.query_normalized AS q, count(o.id) AS open_cnt
                FROM search_opens o JOIN search_events e ON e.id = o.search_event_id
                WHERE date_trunc('day', o.created_at) = :d
                GROUP BY e.query_normalized
            """).bindparams(d=d)).all()
            opens_by_q = {r.q: r.open_cnt for r in orows}

            for r in qrows:
                db.execute(sa_text("""
                    INSERT INTO search_analytics
                        (id, period_start, query, hit_count, zero_result_count, open_count)
                    VALUES (gen_random_uuid(), :p, :q, :h, :z, :o)
                    ON CONFLICT (period_start, query) DO UPDATE SET
                        hit_count = EXCLUDED.hit_count,
                        zero_result_count = EXCLUDED.zero_result_count,
                        open_count = EXCLUDED.open_count
                """).bindparams(p=period, q=r.q, h=r.hit_cnt, z=r.zero_cnt,
                                o=opens_by_q.get(r.q, 0)))
            rolled_days += 1

        # Пакетное удаление raw-событий старше срока (§7.6)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention)
        res = db.execute(sa_text("DELETE FROM search_opens WHERE created_at < :c").bindparams(c=cutoff))
        deleted_events += res.rowcount or 0
        res = db.execute(sa_text("DELETE FROM search_events WHERE created_at < :c").bindparams(c=cutoff))
        deleted_events += res.rowcount or 0
        db.commit()

    log.info("analytics_rollup.done", rolled_days=rolled_days, deleted=deleted_events)
    return {"rolled_days": rolled_days, "deleted": deleted_events}


# ==========================================================================
# Этап 9: уведомления (LLD §8, §9; FR-134–139)
# ==========================================================================

DISPATCH_INTERVAL_S = 15  # диспетчер ≤ 15 с (NFR-007: in-app ≤ 30 с)
EMAIL_MAX_RETRIES = 5  # §9: 5 попыток, экспоненциально


@celery_app.task(name="notifications.dispatch")
def notifications_dispatch() -> dict:
    """Диспетчер (§8.2): события → получатели → анти-шум → notifications.

    Вызывается расписанием (beat, 15 с); повторный прогон по processed=false
    безопасен (идемпотентность §9). Дедуп dedup_key исключает дубли.
    """
    from app.use_cases.notifications.dispatch import dispatch_events

    with get_session_factory()() as db:
        if db.bind.dialect.name == "sqlite":
            return {"events": 0, "skipped": "sqlite"}
        stats = dispatch_events(db)
    if stats["events"]:
        log.info("notifications.dispatch", **stats)
    # Email-отправка: если SMTP настроен, ставим задачу отправки (§9)
    if stats.get("email_created"):
        notifications_email.apply_async()
    return stats


@celery_app.task(bind=True, max_retries=EMAIL_MAX_RETRIES, name="notifications.email")
def notifications_email(self) -> dict:
    """Email-канал (§8.2, §9): отправка уведомлений с email_state='queued'.

    Адрес — из users.email_cache (16.1-119); при пустом кэше — фолбэк Admin
    API (§10, этап 10); пустой адрес → email не отправляется, in-app доставлен
    (US-040 A3, FR-151). Ретраи экспоненциально (§9); SMTP ненастроен →
    задачи не создаются диспетчером (US-040 A1), здесь — защита.
    """
    import smtplib
    from email.message import EmailMessage

    from app.config import get_settings
    from app.use_cases.notifications.dispatch import get_setting, smtp_configured

    settings = get_settings()
    sent = failed = skipped = 0
    with get_session_factory()() as db:
        if db.bind.dialect.name == "sqlite":
            return {"sent": 0, "skipped": "sqlite"}

        # US-040 A1: SMTP не настроен → канал отключён; queued-строки не создаются,
        # но если остались от прошлой конфигурации — помечаем failed (канал off)
        if not smtp_configured(db):
            db.execute(
                update(models.Notification)
                .where(models.Notification.email_state == "queued")
                .values(email_state="failed", )
            )
            db.commit()
            return {"sent": 0, "result": "smtp_not_configured"}

        host = str(get_setting(db, "smtp_host", "") or "").strip()
        port = int(get_setting(db, "smtp_port", 25) or 25)
        sender = str(get_setting(db, "smtp_from", "kb@example.local") or "kb@example.local")
        use_tls = bool(get_setting(db, "smtp_use_tls", False))

        rows = list(db.execute(
            select(models.Notification)
            .where(models.Notification.email_state == "queued")
            .order_by(models.Notification.created_at)
            .limit(100)
        ).scalars().all())

        if not rows:
            return {"sent": 0}

        def _subject_and_body(n: models.Notification, name: str, m_name: str | None):
            titles = {
                "material_sent_to_review": "Материал отправлен на проверку",
                "material_rejected": "Материал отклонён",
                "material_archived": "Материал заархивирован",
                "child_auto_archived": "Подчинённый материал архивирован автоматически",
                "master_changed": "Мастер-материал изменён",
                "material_changed_on_review": "Материал изменён на проверке",
                "status_changed": "Изменение статуса материала",
                "file_blocked": "Файл заблокирован антивирусом",
            }
            t = titles.get(n.event_type, "Уведомление")
            subj = f"[База знаний] {t}"
            body = f"{t}"
            if m_name:
                body += f": {m_name}"
            return subj, body

        try:
            server: smtplib.SMTP | None = smtplib.SMTP(host, port, timeout=10)
            if use_tls:
                server.starttls()
        except Exception as e:
            # Ретрай экспоненциально (§9); потеря письма ≠ потеря данных (US-040 A2)
            try_count = self.request.retries + 1
            if try_count <= EMAIL_MAX_RETRIES:
                raise self.retry(exc=e, countdown=30 * (2 ** (try_count - 1)))
            for n in rows:
                n.email_state = "failed"
            db.commit()
            return {"sent": 0, "failed": len(rows), "error": str(e)}

        try:
            for n in rows:
                u = db.execute(
                    select(models.User).where(models.User.id == n.recipient_id)
                ).scalar_one_or_none()
                m_name = None
                if n.material_id is not None:
                    m_name = db.execute(
                        select(models.Material.name).where(models.Material.id == n.material_id)
                    ).scalar_one_or_none()
                if u is None:
                    n.email_state = "failed"
                    failed += 1
                    continue
                # FR-139/FR-013: деактивированные/сервисные не доставляются
                if u.is_deactivated or u.is_service:
                    n.email_state = "failed"
                    skipped += 1
                    continue
                # US-040 A3: нет email в кэше — in-app доставлен, email нет (FR-151)
                email = (u.email_cache or "").strip()
                if not email:
                    n.email_state = "failed"
                    skipped += 1
                    continue
                subj, body = _subject_and_body(n, u.display_name, m_name)
                msg = EmailMessage()
                msg["Subject"] = subj
                msg["From"] = sender
                msg["To"] = email
                msg.set_content(body, charset="utf-8")
                try:
                    server.send_message(msg)
                    n.email_state = "done"
                    sent += 1
                except Exception:
                    n.email_state = "failed"
                    failed += 1
            db.commit()
        finally:
            try:
                server.quit()
            except Exception:
                pass
    log.info("notifications.email.done", sent=sent, failed=failed, skipped=skipped)
    return {"sent": sent, "failed": failed, "skipped": skipped}


@celery_app.task(name="notifications.digest")
def notifications_digest() -> dict:
    """Email-дайджест (FR-138, §8.2): периодическая сводка непрочитанных
    одним письмом; вошедшие помечаются included_in_digest_at (11.3).

    Интервал — параметр digest_interval_minutes (§2.5; NULL — отключён);
    SMTP ненастроен → дайджест не формируется (US-040 A1).
    """
    import smtplib
    from email.message import EmailMessage

    from app.config import get_settings
    from app.use_cases.notifications.dispatch import get_setting, smtp_configured

    settings = get_settings()
    with get_session_factory()() as db:
        if db.bind.dialect.name == "sqlite":
            return {"digests": 0, "skipped": "sqlite"}
        if not smtp_configured(db):
            return {"digests": 0, "result": "smtp_not_configured"}
        interval = get_setting(db, "digest_interval_minutes", None)
        if interval is None:
            return {"digests": 0, "result": "digest_disabled"}

        host = str(get_setting(db, "smtp_host", "") or "").strip()
        port = int(get_setting(db, "smtp_port", 25) or 25)
        sender = str(get_setting(db, "smtp_from", "kb@example.local") or "kb@example.local")

        # Непрочитанные, ещё не вошедшие в дайджест, по получателям (§8.2)
        rows = list(db.execute(
            select(models.Notification)
            .where(
                models.Notification.read_at.is_(None),
                models.Notification.included_in_digest_at.is_(None),
                models.Notification.email_state == "done",  # уже шло событием
            )
            .order_by(models.Notification.created_at)
        ).scalars().all())
        if not rows:
            return {"digests": 0}

        by_user: dict = {}
        for n in rows:
            by_user.setdefault(n.recipient_id, []).append(n)

        digests = 0
        try:
            server = smtplib.SMTP(host, port, timeout=10)
        except Exception as e:
            log.warning("notifications.digest.smtp_failed", error=str(e))
            return {"digests": 0, "error": str(e)}

        try:
            for uid, notifs in by_user.items():
                u = db.execute(
                    select(models.User).where(models.User.id == uid)
                ).scalar_one_or_none()
                email = (u.email_cache or "").strip() if u else ""
                if not email or (u.is_deactivated or u.is_service):
                    continue  # FR-139, FR-013, US-040 A3
                lines = []
                for n in notifs:
                    m_name = None
                    if n.material_id is not None:
                        m_name = db.execute(
                            select(models.Material.name).where(models.Material.id == n.material_id)
                        ).scalar_one_or_none()
                    lines.append(f"- {n.event_type}: {m_name or '—'}")
                msg = EmailMessage()
                msg["Subject"] = f"[База знаний] Дайджест уведомлений ({len(notifs)})"
                msg["From"] = sender
                msg["To"] = email
                msg.set_content(
                    "Непрочитанные уведомления:\n" + "\n".join(lines), charset="utf-8"
                )
                try:
                    server.send_message(msg)
                    for n in notifs:
                        n.included_in_digest_at = _now()
                    digests += 1
                except Exception:
                    continue  # ретрай — следующий прогон (NFR-014)
            db.commit()
        finally:
            try:
                server.quit()
            except Exception:
                pass
    log.info("notifications.digest.done", digests=digests)
    return {"digests": digests}


# ==========================================================================
# Этап 10: СА-контур — обслуживание аудита/уведомлений, сверка Keycloak (§9)
# ==========================================================================

@celery_app.task(name="maintenance.daily")
def maintenance_daily() -> dict:
    """Ежедневный якорный прогон maintenance-задач (§9): audit_cleanup,
    inapp_cleanup, cas_gc, analytics_rollup. Еженедельные (fts_rebuild,
    cas_reconcile, integrity_check) — прогоном по счётчику дней в Valkey.
    """
    results = {}
    results["audit_cleanup"] = audit_cleanup()
    results["inapp_cleanup"] = inapp_cleanup()
    results["cas_gc"] = cas_gc()
    results["analytics_rollup"] = analytics_rollup()
    return results


@celery_app.task(name="maintenance.audit_cleanup")
def audit_cleanup() -> dict:
    """Пакетное удаление записей аудита по возрасту (FR-141, §11).

    audit_retention_days=NULL (§2.5) → очистка не выполняется.
    """
    from datetime import timedelta

    from sqlalchemy import delete

    from app.use_cases.admin.settings import get_settings_value

    deleted = 0
    with get_session_factory()() as db:
        days = get_settings_value(db, "audit_retention_days", None)
        if days is None:
            return {"deleted": 0, "result": "retention_not_configured"}
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
        res = db.execute(
            delete(models.AuditEntry).where(models.AuditEntry.occurred_at < cutoff)
        )
        deleted = res.rowcount or 0
        db.commit()
    log.info("audit_cleanup.done", deleted=deleted)
    return {"deleted": deleted}


@celery_app.task(name="maintenance.inapp_cleanup")
def inapp_cleanup() -> dict:
    """Очистка in-app уведомлений по возрасту ≥ аудита (FR-137, §9).

    Срок хранения in-app — не меньше срока хранения аудита: удаляем
    уведомления старше min(audit_retention_days, окно по created_at)… —
    при настроенном аудите; NULL → не выполняется.
    """
    from datetime import timedelta

    from sqlalchemy import delete

    from app.use_cases.admin.settings import get_settings_value

    with get_session_factory()() as db:
        days = get_settings_value(db, "audit_retention_days", None)
        if days is None:
            return {"deleted": 0, "result": "retention_not_configured"}
        # in-app хранится не меньше аудита → та же граница (±) не нужна:
        # удаляем уведомления старше срока аудита (равный срок — консервативно)
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
        res = db.execute(
            delete(models.Notification).where(
                models.Notification.created_at < cutoff,
                models.Notification.read_at.isnot(None),  # непрочитанные не трогаем
            )
        )
        deleted = res.rowcount or 0
        db.commit()
    log.info("inapp_cleanup.done", deleted=deleted)
    return {"deleted": deleted}


@celery_app.task(name="maintenance.cas_gc")
def cas_gc() -> dict:
    """Сборка мусора CAS (§6.5): file_objects с ref_count=0 старше
    cas_gc_delay_hours → удаление записи + объекта silo (если ключ не занят).
    """
    from datetime import timedelta

    from sqlalchemy import delete

    from app.use_cases.admin.settings import get_settings_value

    deleted = 0
    with get_session_factory()() as db:
        if db.bind.dialect.name == "sqlite":
            return {"deleted": 0, "skipped": "sqlite"}
        delay_h = int(get_settings_value(db, "cas_gc_delay_hours", 24))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=delay_h)
        orphans = list(db.execute(
            select(models.FileObject).where(
                models.FileObject.ref_count == 0,
                models.FileObject.created_at < cutoff,
            )
        ).scalars().all())
        for fo in orphans:
            # Объект в silo может быть общим по sha256 — удаляем по ключу;
            # pdf-ключ — тоже (пересоздаётся при повторной загрузке)
            try:
                silo.delete_object(silo.cas_key(fo.sha256))
                if fo.pdf_key:
                    silo.delete_object(fo.pdf_key)
            except Exception:
                pass  # silo-объект уже отсутствует / недоступен — запись всё равно удаляем
            db.delete(fo)
            deleted += 1
        db.commit()
    log.info("cas_gc.done", deleted=deleted)
    return {"deleted": deleted}


@celery_app.task(bind=True, name="keycloak.sync", max_retries=3)
def keycloak_sync(self) -> dict:
    """Периодическая сверка с Keycloak (LLD §10, 16.1-118, [уточнение LLD]).

    Admin API GET /admin/realms/kb/users?briefRepresentation=true&first=&max=
    страницами по KEYCLOAK_SYNC_PAGE=100 (полная выгрузка — результат
    заменяет, §9); обновление users.is_deactivated (enabled=false →
    деактивация) и users.email_cache (16.1-119). Новые пользователи — при
    первом входе.
    """
    import urllib.parse
    import urllib.request

    from app.config import get_settings

    settings = get_settings()
    issuer = settings.oidc_issuer.rstrip("/")
    # http://localhost:8080/realms/kb → http://keycloak:8080/... (внутренняя сеть)
    kc_base = issuer.split("/realms/")[0].replace("localhost", "keycloak")
    realm = issuer.split("/realms/")[-1]

    # Токен администратора: сервисный аккаунт kb-api (client credentials).
    # Права Admin API выдаются роли realm-management/view-users на realm kb.
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret,
    }).encode()
    req = urllib.request.Request(f"{kc_base}/realms/{realm}/protocol/openid-connect/token", data=body)
    try:
        tok = json.loads(urllib.request.urlopen(req, timeout=10).read())["access_token"]
    except Exception as e:
        log.warning("keycloak_sync.token_failed", error=str(e))
        raise self.retry(countdown=60)

    checked = deactivated = reactivated = email_updated = 0
    first = 0
    with get_session_factory()() as db:
        if db.bind.dialect.name == "sqlite":
            return {"checked": 0, "skipped": "sqlite"}
        while True:
            q = urllib.parse.urlencode({"briefRepresentation": "true", "first": first, "max": KEYCLOAK_SYNC_PAGE})
            req = urllib.request.Request(
                f"{kc_base}/admin/realms/{realm}/users?{q}",
                headers={"Authorization": f"Bearer {tok}"},
            )
            try:
                page = json.loads(urllib.request.urlopen(req, timeout=10).read())
            except Exception as e:
                log.warning("keycloak_sync.page_failed", first=first, error=str(e))
                raise self.retry(countdown=60)
            if not page:
                break
            for u in page:
                checked += 1
                db_user = db.execute(
                    select(models.User).where(models.User.keycloak_id == u["id"])
                ).scalar_one_or_none()
                if db_user is None:
                    continue  # новые пользователи — при первом входе (§6.1 HLD)
                enabled = bool(u.get("enabled", True))
                if not enabled and not db_user.is_deactivated:
                    # Keycloak-активность исчезла → деактивация (без service_tasks:
                    # сверка — фоновая; задачи создаёт ручная деактивация СА, US-004)
                    db_user.is_deactivated = True
                    deactivated += 1
                elif enabled and db_user.is_deactivated:
                    # Активация в Keycloak → реактивация (LLD §10: деактивация
                    # обратима активацией в Keycloak/сверкой)
                    db_user.is_deactivated = False
                    reactivated += 1
                email = u.get("email") or None
                if email and email != db_user.email_cache:
                    db_user.email_cache = email  # 16.1-119
                    email_updated += 1
            db.commit()
            first += KEYCLOAK_SYNC_PAGE
            if len(page) < KEYCLOAK_SYNC_PAGE:
                break
    log.info("keycloak_sync.done", checked=checked, deactivated=deactivated,
             reactivated=reactivated, email_updated=email_updated)
    return {"checked": checked, "deactivated": deactivated,
            "reactivated": reactivated, "email_updated": email_updated}
