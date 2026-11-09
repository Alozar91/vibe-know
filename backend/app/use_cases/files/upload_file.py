# Загрузка/замена файла материала (LLD §6.2, FR-029–031, FR-057; US-007/008/009).
#
# Поток: multipart → mime по магическим байтам (FR-057) → sha256 поточно →
# дедуп по sha256: found ready → привязка + ref_count+1 (повторный антивирус
# не выполняется — FR-057/NFR-010); infected → 409 FILE_BLOCKED;
# scanning/pending_scan → 409 FILE_PENDING_SCAN; not found → S3 PUT +
# INSERT pending_scan + задача files.scan. Гонка двух загрузок: проигравший
# INSERT повторяет SELECT (уникальность sha256) и привязывается по состоянию.
# Текстовые файлы (text/*, HTML исключён — 16.1-112): автозаполнение при
# пустом тексте (16.1-110); при непустом — text_out_of_sync=true (FR-030:
# решение пользователя — через диалог; API возвращает предложение).
from __future__ import annotations

import codecs
import hashlib
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.errors import DomainError
from app.use_cases.files import silo
from app.use_cases.files.mime_detect import detect_mime, is_text_mime
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.materials.get_material import get_material_or_404
from app.use_cases.materials.versions import commit_version
from app.use_cases.permissions.can import can

MAX_SIZE_MB = 100  # file_max_size_mb (§2.5, FR-031); реестр параметров — этап 10


def _status_v(m: models.Material) -> str:
    return m.status.value if hasattr(m.status, "value") else str(m.status)


def _bind_file(db: Session, m: models.Material, fo: models.FileObject) -> None:
    """Привязка к материалу: ref_count + 1 атомарным UPDATE (§6.2 «атомарный UPDATE»)."""
    m.current_file_id = fo.id
    db.execute(
        update(models.FileObject)
        .where(models.FileObject.id == fo.id)
        .values(ref_count=models.FileObject.ref_count + 1)
    )
    db.refresh(fo)


def upload_file(
    db: Session,
    user,
    material_id: str,
    filename: str,
    data: bytes,
    text_update_choice: str | None = None,  # 'replace' | 'keep' — ответ на предложение FR-030
) -> dict:
    """Загрузка/замена файла (§6.2). Возвращает file_state + подсказку для диалога."""
    m = get_material_or_404(db, user, material_id)
    if not can(db, user, m.id, "edit"):
        from app.use_cases.errors import access_denied

        raise access_denied("Нет права «Редактирование» на материал")
    if _status_v(m) == "archived":
        from app.use_cases.errors import access_denied

        raise access_denied("Материал в архиве; редактирование запрещено")

    # FR-031: лимит размера (параметр file_max_size_mb)
    if len(data) > MAX_SIZE_MB * 1024 * 1024:
        raise DomainError(
            status=413, code="FILE_TOO_LARGE", title="Файл слишком большой",
            detail=f"Размер файла превышает {MAX_SIZE_MB} МБ",
        )
    if not data:
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail="Файл пуст",
        )

    # FR-057: mime по содержимому (магические байты), sha256
    mime = detect_mime(data, filename)
    sha_hex = hashlib.sha256(data).hexdigest()

    # §4.2/§4.3: замена файла в published/approved → возврат в draft (FR-084);
    # мастер с подчинёнными в «Публикации» — блокировка (FR-041)
    status_before = _status_v(m)
    if status_before in ("published", "approved") and m.master_id is None:
        from app.use_cases.materials.update_material import _block_master_with_published_children

        _block_master_with_published_children(db, m)

    # --- Дедупликация по sha256 (§6.2, NFR-010) ---
    fo = db.execute(
        select(models.FileObject).where(models.FileObject.sha256 == sha_hex)
    ).scalar_one_or_none()

    if fo is None:
        fo, ref = _create_file_object(db, filename, mime, sha_hex, data)
        if ref:
            # after-commit постановка в брокер (см. _enqueue_scan)
            if not hasattr(db, "_pending_task_refs"):
                db._pending_task_refs = []
            db._pending_task_refs.append(ref)
    else:
        # found: привязка по состоянию (§6.2); повторный антивирус не выполняется
        if fo.scan_state == "infected":
            raise DomainError(
                status=409, code="FILE_BLOCKED", title="Файл заблокирован",
                detail="Файл не прошёл антивирусную проверку",
            )
        if fo.scan_state in ("scanning", "pending_scan"):
            raise DomainError(
                status=409, code="FILE_PENDING_SCAN", title="Файл ещё проверяется",
                detail="Файл проходит антивирусную проверку; повторите позже",
            )

    _bind_file(db, m, fo)

    # --- Текстовое представление (§6.2 п.3, FR-029/030, 16.1-110/112) ---
    text_filled_automatically = False
    offer_update = False
    if is_text_mime(mime) and mime != "text/html":
        decoded = _decode_text(data)
        if decoded is not None:
            if not m.text_content:
                # автозаполнение при пустом тексте (16.1-110)
                m.text_content = decoded
                m.text_out_of_sync = False
                text_filled_automatically = True
            elif decoded != m.text_content:
                if text_update_choice == "replace":
                    m.text_content = decoded
                    m.text_out_of_sync = False
                else:
                    # FR-030: при непустом — предложение; до решения пользователя
                    # текст сохраняется, ставится признак рассинхронизации
                    if text_update_choice == "keep":
                        m.text_out_of_sync = True
                    offer_update = True
                    m.text_out_of_sync = True

    # --- §4.2: замена файла — правка контента по статусам (FR-084) ---
    now = datetime.now(timezone.utc)
    new_status = status_before
    if status_before in ("published", "approved"):
        new_status = "draft"
    if new_status != status_before:
        from app.use_cases.lifecycle.status_log import write_status_log

        write_status_log(db, user, m, status_before, new_status)
        audit_log(
            db, user, "material.status_change", "material", m.id,
            details={"from": status_before, "to": new_status, "reason": "file_replaced"},
        )
        m.status = models.MaterialStatus(new_status)
        m.signatory_id = None  # FR-084
        m.signatory_at = None
    elif status_before == "in_review":
        # FR-085: аудит правки на ревью; уведомление — этап 9
        audit_log(db, user, "material.update", "material", m.id,
                  details={"on_review": True, "file_replaced": True})
    audit_log(db, user, "file_upload", "material", m.id,
              details={"file_id": str(fo.id), "sha256": sha_hex, "mime": mime,
                       "size": len(data), "filename": filename})

    m.last_editor_id = user.user_id
    m.version += 1
    m.updated_at = now

    # Фиксация версии: замена файла — новый file_id (§5.1, FR-147)
    commit_version(db, m, user)

    pending_enqueue = [ref for ref in (getattr(db, "_pending_task_refs", None) or [])]
    db.commit()

    # Постановка в брокер — после коммита (задача видит зафиксированные строки);
    # сбой брокера не мешает ответу: task остаётся queued, подхватит reconcile (§9)
    if pending_enqueue:
        from app.worker.tasks import files_scan

        for _kind, task_id, file_id in pending_enqueue:
            try:
                files_scan.apply_async(args=[task_id, file_id])
            except Exception:
                pass

    return {
        "id": str(m.id),
        "version": m.version,
        "file_state": file_state(fo),
        "text_filled_automatically": text_filled_automatically,
        "offer_text_update": offer_update,
        "text_out_of_sync": m.text_out_of_sync,
    }


def _enqueue_scan(db: Session, fo: models.FileObject) -> tuple:
    """system_tasks queued (NFR-014, источник истины). Celery — ПОСЛЕ коммита
    (гонка: worker читает БД до фиксации INSERT → «missing» → вечный pending).
    Возвращает кортеж-ссылку для after-commit отправки."""
    task = models.SystemTask(
        task_type="antivirus", object_type="file", object_id=fo.id, state="queued"
    )
    db.add(task)
    db.flush()
    return ("antivirus", str(task.id), str(fo.id))


def _create_file_object(
    db: Session, filename: str, mime: str, sha_hex: str, data: bytes
) -> tuple:
    """Not found: S3 PUT + INSERT pending_scan + system_tasks queued (§6.2 п.2).

    Возвращает (FileObject, ref|None); ref — кортеж-ссылка (kind, task_id,
    file_id) для after-commit отправки в брокер.
    """
    silo.put_object(silo.cas_key(sha_hex), data, content_type=mime)
    fo = models.FileObject(
        cas_key=sha_hex,  # существующая модель: cas_key = sha256 (UNIQUE, этап 4)
        filename=filename,
        mime_type=mime,
        size_bytes=len(data),
        sha256=sha_hex,
        scan_state="pending_scan",
        pdf_state="none",
        ref_count=0,  # инкремент только при фактической привязке (§6.2)
    )
    db.add(fo)
    try:
        db.flush()
    except Exception:
        # Гонка двух одновременных загрузок (§6.2): уникальность sha256 —
        # проигравший INSERT повторяет SELECT и привязывается по состоянию
        db.rollback()
        fo = db.execute(
            select(models.FileObject).where(models.FileObject.sha256 == sha_hex)
        ).scalar_one_or_none()
        if fo is None:
            raise
        if fo.scan_state == "infected":
            raise DomainError(
                status=409, code="FILE_BLOCKED", title="Файл заблокирован",
                detail="Файл не прошёл антивирусную проверку",
            )
        if fo.scan_state in ("scanning", "pending_scan"):
            raise DomainError(
                status=409, code="FILE_PENDING_SCAN", title="Файл ещё проверяется",
                detail="Файл проходит антивирусную проверку; повторите позже",
            )
        return fo, None
    ref = _enqueue_scan(db, fo)
    return fo, ref


def _decode_text(data: bytes) -> str | None:
    """Декодирование текстового файла (UTF-8 BOM/без, UTF-16 BOM, cp1251 fallback)."""
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace")
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1251")
        except UnicodeDecodeError:
            return None


def file_state(fo: models.FileObject) -> dict:
    """Состояние конвейера файла (§6.3, GET /materials/{id}/file-state)."""
    return {
        "file_id": str(fo.id),
        "filename": fo.filename,
        "mime_type": fo.mime_type,
        "size_bytes": fo.size_bytes,
        "scan_state": fo.scan_state,
        "pdf_state": fo.pdf_state,
    }
