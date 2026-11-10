# Проверки прав §3.2 на одиночном материале/группе (US-045, FR-129).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.permissions.eff import (
    DRAFT_STATUSES,
    PROCESS_PERMS,
    PUBLIC_STATUSES,
    eff_rows,
    group_chain_ids,
    has_right,
)


def _visible(eff, status: str, is_author: bool) -> bool:
    """Ветки видимости §3.2 (FR-066): черновик/процесс — автор и носители прав;
    публикация/архив — носители view."""
    if status in DRAFT_STATUSES:
        return is_author or any(has_right(eff, p) for p in PROCESS_PERMS)
    if status in PUBLIC_STATUSES:
        return has_right(eff, "view")
    return False


def can(db: Session, user, material_id, permission: str) -> bool:
    """Право на материал (§3.2 «та же логика через can»)."""
    if user.is_super:
        return True  # FR-104
    from app.use_cases.common import parse_uuid

    mid = parse_uuid(str(material_id))
    if mid is None:
        return False
    row = db.execute(
        select(models.Material.status, models.Material.author_id, models.Material.group_id)
        .where(models.Material.id == mid)
    ).first()
    if row is None:
        return False
    status, author_id, group_id = row
    status_v = status.value if hasattr(status, "value") else str(status)
    gpath = db.execute(
        select(models.Group.path).where(models.Group.id == group_id)
    ).scalar_one_or_none()
    eff = eff_rows(db, user.user_id, group_chain_ids(db, gpath), material_id=material_id)
    if not _visible(eff, status_v, author_id == user.user_id):
        return False
    # Хвост §3.2: view не требует отдельного правила (видимость уже проверена);
    # иное действие — по праву (FR-102)
    return True if permission == "view" else has_right(eff, permission)


def can_group(db: Session, user, group_id, permission: str) -> bool:
    """Право на группу: view — отображение с содержимым (FR-103); create — US-007."""
    if user.is_super:
        return True
    from app.use_cases.common import parse_uuid

    gid = parse_uuid(str(group_id))
    if gid is None:
        return False
    gpath = db.execute(
        select(models.Group.path).where(
            models.Group.id == gid, models.Group.is_deleted.is_(False)
        )
    ).scalar_one_or_none()
    if gpath is None:
        return False
    eff = eff_rows(db, user.user_id, group_chain_ids(db, gpath))
    return has_right(eff, permission)


def effective_permissions(db: Session, user, material_id) -> dict[str, bool]:
    """Карта прав материала для карточки/UI (FR-129): один eff-набор на все права."""
    if user.is_super:
        return {p: True for p in PERMISSIONS_CATALOG}
    row = db.execute(
        select(models.Material.status, models.Material.author_id, models.Material.group_id)
        .where(models.Material.id == material_id)
    ).first()
    if row is None:
        return {p: False for p in PERMISSIONS_CATALOG}
    status, author_id, group_id = row
    status_v = status.value if hasattr(status, "value") else str(status)
    gpath = db.execute(
        select(models.Group.path).where(models.Group.id == group_id)
    ).scalar_one_or_none()
    eff = eff_rows(db, user.user_id, group_chain_ids(db, gpath), material_id=material_id)
    out: dict[str, bool] = {}
    for p in PERMISSIONS_CATALOG:
        visible = _visible(eff, status_v, author_id == user.user_id)
        out[p] = visible and (True if p == "view" else has_right(eff, p))
    return out


from app.use_cases.permissions.eff import PERMISSIONS_CATALOG  # noqa: E402
