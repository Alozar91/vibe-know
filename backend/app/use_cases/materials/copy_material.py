# Use-case: копирование материала (LLD §4.3, 7.10; US-028; FR-092).
#
# Любой статус исходника, включая «Архив»; право «Копирование» на исходном +
# «Создание» в целевой группе; новый материал — черновик с копией файла
# (ref_count+1, без повторного антивируса — FR-057), текста, типа, атрибутов
# и тегов; имя «<имя> Копия» со счётчиком; master_id сохраняется, если мастер
# исходника не в архиве, иначе NULL; подчинённые не копируются (FR-092).
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid
from app.use_cases.errors import access_denied, not_found
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.materials.create_material import require_group_create
from app.use_cases.materials.dto import to_out
from app.use_cases.materials.get_material import get_material_or_404
from app.use_cases.materials.stage7_common import commit_first_version, copy_content, unique_name

COPY_SUFFIX = " Копия"


def copy_material(db: Session, user, material_id: str, target_group_id: str) -> dict:
    """Копирование материала (US-028)."""
    from app.use_cases.permissions.can import can

    src = get_material_or_404(db, user, material_id)
    if not can(db, user, src.id, "copy"):
        raise access_denied("Нет права «Копирование» на материал")

    # Целевая группа: create (FR-092/FR-108)
    g = require_group_create(db, user, target_group_id)

    final_name = unique_name(db, g.id, f"{src.name}{COPY_SUFFIX}")

    # master_id копии: сохраняется, если мастер исходника не в архиве (FR-092)
    master_id = None
    if src.master_id is not None:
        master = db.execute(
            select(models.Material).where(models.Material.id == src.master_id)
        ).scalar_one_or_none()
        if master is not None and not master.is_deleted:
            ms = master.status.value if hasattr(master.status, "value") else str(master.status)
            if ms != "archived":
                master_id = master.id

    now = datetime.now(timezone.utc)
    from app.use_cases.groups.create_group import normalize_name

    cp = models.Material(
        group_id=g.id,
        name=final_name,
        normalized_name=normalize_name(final_name),
        type_id=src.type_id,
        status=models.MaterialStatus.draft,
        master_id=master_id,
        author_id=user.user_id,
        last_editor_id=user.user_id,
        version=1,
        updated_at=now,
    )
    db.add(cp)
    db.flush()

    copy_content(db, src, cp)
    commit_first_version(db, cp, user)

    audit_log(db, user, "material.copy", "material", cp.id,
              details={"source_id": str(src.id), "source_status": (
                  src.status.value if hasattr(src.status, "value") else str(src.status)
              )})

    db.commit()
    return to_out(cp)
