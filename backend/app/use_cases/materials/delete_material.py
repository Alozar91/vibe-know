# Use-case: удаление материала (soft, FR-090; US-023 — этап 7 уточнит мастера).
# Этап 4: soft-delete + право delete; запрет мастеру с подчинёнными (FR-040) —
# подчинённых до этапа 7 не бывает, проверка оставлена (hasattr).
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.errors import DomainError, access_denied, domain_rule_violation
from app.use_cases.materials.get_material import get_material_or_404
from app.use_cases.permissions.can import can


def delete_material(db: Session, user, material_id: str, if_match: str | None) -> dict:
    m = get_material_or_404(db, user, material_id)
    if not can(db, user, m.id, "delete"):
        raise access_denied("Нет права «Удаление» на материал")
    if if_match is None or not if_match.strip():
        raise DomainError(
            status=428, code="PRECONDITION_REQUIRED", title="Требуется If-Match",
            detail="Передайте заголовок If-Match с текущей версией материала",
        )
    try:
        expected = int(if_match.strip().strip('"'))
    except ValueError:
        raise domain_rule_violation(400, "If-Match должен содержать номер версии")
    if m.version != expected:
        raise DomainError(
            status=412, code="VERSION_CONFLICT", title="Конфликт версии",
            detail=f"Материал изменён (текущая версия {m.version})",
        )

    # FR-090: удаление — только из draft/in_review (этап 5 включит в валидатор
    # переходов; здесь — прямая проверка)
    status_v = m.status.value if hasattr(m.status, "value") else str(m.status)
    if status_v not in ("draft", "in_review"):
        raise domain_rule_violation(
            409, "Удаление возможно только из статусов «Черновик» и «На проверке»"
        )
    # FR-040: мастер с неудалёнными подчинёнными не удаляется
    child = db.execute(
        select(models.Material.id).where(
            models.Material.master_id == m.id, models.Material.is_deleted.is_(False)
        ).limit(1)
    ).first()
    if child:
        raise DomainError(
            status=409, code="MASTER_DELETE_FORBIDDEN", title="Удаление невозможно",
            detail="У материала есть подчинённые",
        )

    m.is_deleted = True
    m.deleted_at = datetime.now(timezone.utc)
    m.version += 1
    db.commit()
    return {"id": str(m.id), "deleted": True, "version": m.version}
