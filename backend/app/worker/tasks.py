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
