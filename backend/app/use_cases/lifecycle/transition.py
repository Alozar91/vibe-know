# Use-case: переход статуса (LLD §4.1; US-015–021, US-054).
#
# Цепочка валидаторов (порядок фиксирован, FR-077):
#   1) оптимистичная блокировка If-Match/version (FR-093–095) — 428/412;
#   2) правило матрицы + права перехода (FR-070–072, default deny);
#   3) файл обязателен для in_review/approved/published (FR-028/076);
#   4) антивирус: file_objects.scan_state = 'ready' (FR-058);
#   5) мастер-зависимости: подчинённый не публикуется раньше мастера (FR-042),
#      мастер с подчинёнными в «Публикации» не меняет статус кроме → archived (FR-041);
#   6) каскадная архивация (FR-039): без confirm_cascade → 409 CASCADE_CONFIRM_REQUIRED.
# Фиксация (одна транзакция): новый статус, подписант при →approved (FR-068) и
# очистка при возврате в draft (FR-082/084), published_at/archived_at,
# status_log (FR-075), аудит material.status_change, version += 1.
from datetime import datetime, timezone
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.errors import (
    DomainError,
    cascade_confirm_required,
    file_not_ready,
    file_required,
    master_not_published,
    master_status_locked,
    transition_not_allowed,
)
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.lifecycle.status_log import write_status_log
from app.use_cases.materials.get_material import get_material_or_404
from app.use_cases.permissions.eff import eff_rows, group_chain_ids, has_right

# Статусы, требующие файла для входа (FR-076)
_FILE_REQUIRED_TO = ("in_review", "approved", "published")


def _require_if_match(if_match: str | None) -> None:
    """Мутация без If-Match — 428 (FR-095, LLD §12.1)."""
    if if_match is None or not if_match.strip():
        raise DomainError(
            status=428, code="PRECONDITION_REQUIRED", title="Требуется If-Match",
            detail="Передайте заголовок If-Match с текущей версией материала",
        )


def _parse_version(if_match: str) -> int:
    v = if_match.strip().strip('"')
    try:
        return int(v)
    except ValueError:
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail="If-Match должен содержать номер версии",
        )


def _check_version(m: models.Material, expected: int) -> None:
    """Конкурентные смены статуса (FR-094): не совпало → 412."""
    if m.version != expected:
        raise DomainError(
            status=412, code="VERSION_CONFLICT", title="Конфликт версии",
            detail=f"Материал изменён (текущая версия {m.version}); повторите переход от актуальной",
        )


def _find_rule(db: Session, from_status: str, to_status: str) -> models.TransitionRule | None:
    """Строка матрицы: точное правило; иначе «*» (from_status IS NULL)."""
    row = db.execute(
        select(models.TransitionRule).where(
            models.TransitionRule.from_status == from_status,
            models.TransitionRule.to_status == to_status,
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    return db.execute(
        select(models.TransitionRule).where(
            models.TransitionRule.from_status.is_(None),
            models.TransitionRule.to_status == to_status,
        )
    ).scalar_one_or_none()


def _rule_allows(rule: models.TransitionRule, eff: dict, is_super: bool) -> bool:
    """Права перехода (FR-070/072): любого из прав правила достаточно;
    правило без прав — только СА (default deny, 8.3)."""
    if is_super:
        return True
    perms = [
        (p.permission.value if hasattr(p.permission, "value") else str(p.permission))
        for p in rule.permissions
    ]
    if not perms:
        return False
    return any(has_right(eff, p) for p in perms)


def _status_v(status) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _check_file(db: Session, m: models.Material, to_status: str) -> None:
    """Валидаторы 3–4: файл обязателен (FR-028/076), scan_state='ready' (FR-058)."""
    if to_status not in _FILE_REQUIRED_TO:
        return
    if m.current_file_id is None:
        raise file_required()
    fo = db.execute(
        select(models.FileObject).where(models.FileObject.id == m.current_file_id)
    ).scalar_one()
    if fo.scan_state != "ready":
        raise file_not_ready()


def _check_master(db: Session, m: models.Material, to_status: str) -> None:
    """Валидатор 5: мастер-зависимости (FR-041, FR-042)."""
    if m.master_id is not None:
        # Подчинённый: публикация только после мастера (FR-042)
        if to_status == "published":
            master = db.execute(
                select(models.Material).where(models.Material.id == m.master_id)
            ).scalar_one_or_none()
            if master is None or master.is_deleted or _status_v(master.status) != "published":
                raise master_not_published()
    else:
        # Мастер/самостоятельный: с неудалёнными подчинёнными в «Публикации»
        # статус не меняется, кроме «→ Архив» (FR-041)
        if to_status != "archived":
            has_published_children = db.execute(
                select(models.Material.id).where(
                    models.Material.master_id == m.id,
                    models.Material.is_deleted.is_(False),
                    models.Material.status == models.MaterialStatus.published,
                ).limit(1)
            ).first()
            if has_published_children:
                raise master_status_locked()


def _children_count(db: Session, material_id) -> int:
    return db.execute(
        select(func.count())
        .select_from(models.Material)
        .where(models.Material.master_id == material_id, models.Material.is_deleted.is_(False))
    ).scalar_one()


def _cascade_archive(db: Session, m: models.Material, user, now: datetime) -> list[uuid.UUID]:
    """Каскадная архивация подчинённых (FR-039): каждый — отдельная запись
    журнала статусов и аудита (§2.2 status_log, US-021 шаг 5)."""
    children = db.execute(
        select(models.Material).where(
            models.Material.master_id == m.id, models.Material.is_deleted.is_(False)
        )
    ).scalars().all()
    archived_ids = []
    for ch in children:
        ch_from = _status_v(ch.status)
        ch.status = models.MaterialStatus.archived
        ch.archived_at = now
        ch.version += 1
        ch.updated_at = now
        write_status_log(db, user, ch, ch_from, "archived")
        audit_log(
            db, user, "material.status_change", "material", ch.id,
            details={"from": ch_from, "to": "archived", "cascade": True},
        )
        archived_ids.append(ch.id)
    return archived_ids


def transition(
    db: Session,
    user,
    material_id: str,
    to_status: str,
    if_match: str | None,
    confirm_cascade: bool = False,
) -> dict:
    """Смена статуса по матрице (§4.1); возвращает состояние материала."""
    m = get_material_or_404(db, user, material_id)

    # Валидатор 1: If-Match + версия (FR-093–095): 428/400/412
    _require_if_match(if_match)
    expected = _parse_version(if_match)
    _check_version(m, expected)

    if to_status not in [s.value for s in models.MaterialStatus]:
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail=f"Неизвестный статус: {to_status}",
        )

    from_status = _status_v(m.status)
    if to_status == from_status:
        raise transition_not_allowed("Материал уже в целевом статусе")

    # Валидатор 2: правило матрицы + права перехода (FR-070–072)
    rule = _find_rule(db, from_status, to_status)
    if rule is None:
        raise transition_not_allowed("В матрице нет правила для этого перехода")
    eff = eff_rows(db, user.user_id, group_chain_ids(db, m.group.path), material_id=m.id)
    if not _rule_allows(rule, eff, user.is_super):
        raise transition_not_allowed("Нет права на этот переход")

    # Валидаторы 3–4: файл (FR-028/076) и антивирус (FR-058)
    _check_file(db, m, to_status)

    # Валидатор 5: мастер-зависимости (FR-041/042)
    _check_master(db, m, to_status)

    # Валидатор 6: каскадная архивация (FR-039)
    now = datetime.now(timezone.utc)
    cascade_ids: list[str] = []
    if to_status == "archived":
        children_count = _children_count(db, m.id)
        if children_count > 0 and not confirm_cascade:
            raise cascade_confirm_required(children_count)
        if children_count > 0:
            cascade_ids = [str(i) for i in _cascade_archive(db, m, user, now)]

    # --- Фиксация (одна транзакция, §4.1 п.4) ---
    m.status = models.MaterialStatus(to_status)
    if to_status == "approved":
        m.signatory_id = user.user_id  # FR-068: финальный подписант — последний
        m.signatory_at = now
    if to_status == "draft":
        m.signatory_id = None  # FR-082/084: очистка при возврате в «Черновик»
        m.signatory_at = None
    if to_status == "published":
        m.published_at = now  # FR-086
    if to_status == "archived":
        m.archived_at = now
    m.last_editor_id = user.user_id
    m.updated_at = now
    m.version += 1

    write_status_log(db, user, m, from_status, to_status)
    audit_log(
        db, user, "material.status_change", "material", m.id,
        details={"from": from_status, "to": to_status},
    )
    db.commit()
    return {
        "id": str(m.id),
        "status": to_status,
        "version": m.version,
        "signatory_id": str(m.signatory_id) if m.signatory_id else None,
        "signatory_at": m.signatory_at.isoformat() if m.signatory_at else None,
        "published_at": m.published_at.isoformat() if m.published_at else None,
        "archived_at": m.archived_at.isoformat() if m.archived_at else None,
        "cascade_archived": cascade_ids,
    }
