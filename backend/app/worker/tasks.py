# Реестр задач Celery (имена — точно по LLD §9).
# Этап 6: files.scan (заглушка антивируса, 16.1-14), files.convert (Gotenberg).
# Этап 9: notifications.dispatch, notifications.email, notifications.digest.
# Этап 10: maintenance.*, keycloak.sync.
from __future__ import annotations

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
            # Прямое уведомление file_blocked (FR-058) — этап 9; аудит — системный
            _audit_system(db, "file.scan", fo,
                          details={"result": "infected"})
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
