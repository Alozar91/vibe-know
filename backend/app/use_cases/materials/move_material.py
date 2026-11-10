# Use-case: перемещение материала между группами (LLD §12.3; US-027; FR-037).
#
# Права: «Перемещение» в исходной и целевой группах + «Редактирование» на
# материале (FR-037/FR-108); мастер с неудалёнными подчинёнными не
# перемещается (FR-037, §2.3-2); уникальность названия в целевой группе —
# конфликт отклоняется без автопереименования (16.1-66); явные права
# материала сохраняются, наследование пересчитывается по новой цепочке
# (снапшоты прав не трогаем); связь с мастером не меняется. Версии не
# создаются (group_id вне снапшота, FR-144).
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid
from app.use_cases.errors import access_denied, name_conflict, not_found
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.materials.create_material import ensure_name_free
from app.use_cases.materials.get_material import get_material_or_404
from app.use_cases.materials.stage7_common import guard_not_master_with_children


def move_material(db: Session, user, material_id: str, target_group_id: str) -> dict:
    """Перемещение в другую группу (US-027)."""
    from app.use_cases.permissions.can import can, can_group

    m = get_material_or_404(db, user, material_id)
    if not can(db, user, m.id, "edit"):
        raise access_denied("Нет права «Редактирование» на материал")
    # Право move в обеих группах (FR-037)
    if not can_group(db, user, m.group_id, "move"):
        raise access_denied("Нет права «Перемещение» в исходной группе")
    if not can_group(db, user, target_group_id, "move"):
        raise access_denied("Нет права «Перемещение» в целевой группе")

    guard_not_master_with_children(db, m)

    g = db.execute(
        select(models.Group).where(
            models.Group.id == parse_uuid(str(target_group_id)),
            models.Group.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if g is None:
        raise not_found("Группа не найдена")
    if g.id == m.group_id:
        raise access_denied("Материал уже находится в этой группе")
    from_group_id = m.group_id

    # A1 US-027: конфликт названия — без автопереименования (16.1-66)
    try:
        ensure_name_free(db, g.id, m.name, exclude_id=m.id)
    except Exception:
        raise name_conflict(
            "Материал с таким названием уже существует в целевой группе; "
            "переименуйте материал вручную"
        )

    old_group_id = m.group_id
    m.group_id = g.id
    m.last_editor_id = user.user_id
    m.updated_at = datetime.now(timezone.utc)
    m.version += 1

    audit_log(db, user, "material.move", "material", m.id,
              details={"from_group_id": str(old_group_id), "to_group_id": str(g.id)})

    db.commit()
    return {"id": str(m.id), "group_id": str(m.group_id), "version": m.version}
