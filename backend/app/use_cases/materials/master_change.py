# Use-case: смена мастера и отвязка (LLD §12.3; US-026; FR-032/036, 16.1-111).
#
# Право edit на подчинённом (FR-108); новый мастер — «Утверждён»/«Публикация»
# и виден; для подчинённого в «Утверждён»/«Публикация» — только «Публикация»
# (FR-036); циклы/самоссылка/подчинённый-как-мастер запрещены (FR-032).
# Уведомление «мастер изменён» НЕ создаётся (16.1-111: смена ссылки или
# отвязка — не изменение мастер-материала; событие master_changed — этап 9).
# Версии: master_id в снапшот не входит (FR-144), версий не создаёт — но
# version инкрементируется (изменение материала, ETag).
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.errors import DomainError, access_denied
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.materials.get_material import get_material_or_404
from app.use_cases.materials.stage7_common import resolve_new_master


def change_master(
    db: Session, user, material_id: str, new_master_id: str
) -> dict:
    """Смена мастера (US-026 основной поток)."""
    from app.use_cases.permissions.can import can

    m = get_material_or_404(db, user, material_id)
    if not can(db, user, m.id, "edit"):
        raise access_denied("Нет права «Редактирование» на материал")
    if m.master_id is None:
        raise DomainError(
            status=409, code="DOMAIN_RULE_VIOLATION", title="Материал не подчинённый",
            detail="Смена мастера применима к подчинённому материалу",
        )

    master = resolve_new_master(db, user, new_master_id, m)

    now = datetime.now(timezone.utc)
    m.master_id = master.id
    m.last_editor_id = user.user_id
    m.updated_at = now
    m.version += 1

    audit_log(db, user, "material.master_change", "material", m.id,
              details={"new_master_id": str(master.id)})

    db.commit()
    return {"id": str(m.id), "master_id": str(m.master_id), "version": m.version}


def detach_master(db: Session, user, material_id: str) -> dict:
    """Отвязка от мастера (US-026 п.5): master_id → NULL, самостоятельный."""
    from app.use_cases.permissions.can import can

    m = get_material_or_404(db, user, material_id)
    if not can(db, user, m.id, "edit"):
        raise access_denied("Нет права «Редактирование» на материал")
    if m.master_id is None:
        raise DomainError(
            status=409, code="DOMAIN_RULE_VIOLATION", title="Материал не подчинённый",
            detail="Отвязка применима к подчинённому материалу",
        )

    now = datetime.now(timezone.utc)
    old_master_id = m.master_id
    m.master_id = None
    m.last_editor_id = user.user_id
    m.updated_at = now
    m.version += 1

    audit_log(db, user, "material.master_change", "material", m.id,
              details={"detached_from": str(old_master_id)})

    db.commit()
    return {"id": str(m.id), "master_id": None, "version": m.version}
