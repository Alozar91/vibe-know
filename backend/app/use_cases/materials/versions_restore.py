# Восстановление версии (LLD §5.2, FR-148; US-042).
#
# Содержимое снапшота n применяется как правка контента: проходят правила
# §4.2 (в published/approved — возврат в draft, очистка подписанта; in_review —
# статус сохраняется; архив — запрещено, FR-087; мастер с подчинёнными в
# «Публикации» — блокировка FR-041); создаётся новая версия (отката нет —
# FR-148); master_id не меняется (US-042 шаг 4). События уведомлений — как для
# правки контента (US-042 шаг 5, этап 9).
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid
from app.use_cases.errors import DomainError
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.lifecycle.status_log import write_status_log
from app.use_cases.materials.attributes_io import apply_attribute_values
from app.use_cases.materials.get_material import get_material_or_404
from app.use_cases.materials.tags_io import apply_tags
from app.use_cases.materials.versions import commit_version, get_version_or_404
from app.use_cases.permissions.can import can


def _status_v(m: models.Material) -> str:
    return m.status.value if hasattr(m.status, "value") else str(m.status)


def restore_version(
    db: Session, user, material_id: str, number: int, if_match: str | None
) -> dict:
    """Восстановление версии n как правки контента (FR-148)."""
    m = get_material_or_404(db, user, material_id)
    if not can(db, user, m.id, "edit"):
        raise DomainError(
            status=403, code="ACCESS_DENIED", title="Доступ запрещён",
            detail="Нет права «Редактирование» на материал",
        )

    # Мутация без If-Match — 428 (FR-095); конфликт — 412 (FR-093)
    if if_match is None or not if_match.strip():
        raise DomainError(
            status=428, code="PRECONDITION_REQUIRED", title="Требуется If-Match",
            detail="Передайте заголовок If-Match с текущей версией материала",
        )
    try:
        expected = int(if_match.strip().strip('"'))
    except ValueError:
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail="If-Match должен содержать номер версии",
        )
    if m.version != expected:
        raise DomainError(
            status=412, code="VERSION_CONFLICT", title="Конфликт версии",
            detail=f"Материал изменён (текущая версия {m.version}); обновите карточку",
        )

    status_v = _status_v(m)
    if status_v == "archived":
        # FR-087: в архиве редактирование запрещено (US-042 A2)
        raise DomainError(
            status=403, code="ACCESS_DENIED", title="Доступ запрещён",
            detail="Материал в архиве; восстановление версии запрещено",
        )

    v = get_version_or_404(db, m.id, number)
    snap = v.snapshot or {}

    # FR-041: мастер с подчинёнными в «Публикации» — блокировка (US-042 A1)
    if m.master_id is None:
        from sqlalchemy import select as _select

        has_published_children = db.execute(
            _select(models.Material.id).where(
                models.Material.master_id == m.id,
                models.Material.is_deleted.is_(False),
                models.Material.status == models.MaterialStatus.published,
            ).limit(1)
        ).first()
        if has_published_children:
            from app.use_cases.errors import master_status_locked

            raise master_status_locked()

    # --- Применение снапшота как правки (§5.2) ---
    from sqlalchemy import select

    # текст
    m.text_content = snap.get("text")
    # файл: привязка к прежнему FileObject, если он существует (§5.1: дедуп, FR-147);
    # file_id NULL в снапшоте → файл не восстанавливается (остаётся текущий? —
    # по §5.2 восстанавливается содержимое снапшота: файл снимается)
    target_file_id = snap.get("file_id")
    if target_file_id:
        fo = db.execute(
            select(models.FileObject).where(
                models.FileObject.id == parse_uuid(str(target_file_id))
            )
        ).scalar_one_or_none()
        if fo is None:
            raise DomainError(
                status=409, code="FILE_PENDING_SCAN", title="Файл недоступен",
                detail="Файл этой версии отсутствует в хранилище",
            )
        if m.current_file_id != fo.id:
            m.current_file_id = fo.id
            from sqlalchemy import update

            db.execute(
                update(models.FileObject)
                .where(models.FileObject.id == fo.id)
                .values(ref_count=models.FileObject.ref_count + 1)
            )
    # метаданные
    m.name = snap.get("name") or m.name
    m.normalized_name = (m.name or "").strip().lower()
    if snap.get("type_id"):
        m.type_id = parse_uuid(str(snap["type_id"]))

    t = db.execute(
        select(models.MaterialType).where(models.MaterialType.id == m.type_id)
    ).scalar_one_or_none()
    if t is not None and snap.get("attributes") is not None:
        apply_attribute_values(
            db, m, t,
            [
                {"attribute_id": a.get("attribute_id"), "values": a.get("values") or []}
                for a in snap["attributes"]
            ],
        )
    if snap.get("tags") is not None:
        apply_tags(db, m, [str(t) for t in snap["tags"]])

    # --- Правила §4.2: контент → статусы ---
    now = datetime.now(timezone.utc)
    new_status = status_v
    if status_v in ("published", "approved"):
        new_status = "draft"
    if new_status != status_v:
        write_status_log(db, user, m, status_v, new_status)
        audit_log(
            db, user, "material.status_change", "material", m.id,
            details={"from": status_v, "to": new_status, "reason": "version_restore"},
        )
        m.status = models.MaterialStatus(new_status)
        m.signatory_id = None  # FR-084
        m.signatory_at = None
    elif status_v == "in_review":
        # FR-085/US-042 шаг 5: уведомление material_changed_on_review — этап 9
        audit_log(db, user, "material.update", "material", m.id,
                  details={"on_review": True, "restore_version": number})
    else:
        audit_log(db, user, "material.update", "material", m.id,
                  details={"restore_version": number})

    m.last_editor_id = user.user_id
    m.version += 1
    m.updated_at = now

    # Новая версия (FR-148): даже если снапшот совпал с последней? — по §5.1
    # фиксация идёт при различии; restore вернул прежнее состояние → сравнение
    # корректно не создаст дубль; но явное восстановление фиксируется аудитом.
    commit_version(db, m, user)

    db.commit()
    return {"id": str(m.id), "version": m.version, "restored_from": number}
