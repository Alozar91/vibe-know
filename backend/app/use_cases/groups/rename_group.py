# Use-case: переименование группы (FR-015, US-052 шаг 3) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import get_group_or_404, require_super
from app.use_cases.errors import DomainError
from app.use_cases.groups.constants import NAME_MAX_LEN
from app.use_cases.groups.create_group import normalize_name
from app.use_cases.groups.dto import to_out
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.permissions.cache import commit_rights


def rename_group(db: Session, is_super: bool, group_id: str, name: str, actor=None) -> dict:
    """Переименование; path не меняется (перенос/перестроение не предусмотрены, FR-023)."""
    require_super(is_super)
    if not name or not name.strip():
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Название группы обязательно")
    if len(name.strip()) > NAME_MAX_LEN:
        raise DomainError(status=400, code="NAME_TOO_LONG", title="Ошибка валидации запроса",
                          detail=f"Название превышает {NAME_MAX_LEN} символов")

    g = get_group_or_404(db, group_id)
    if g.is_deleted:
        raise DomainError(status=409, code="DOMAIN_RULE_VIOLATION", title="Операция запрещена",
                          detail="Операция над удалённой группой невозможна")

    new_normalized = normalize_name(name)
    if new_normalized != g.normalized_name:
        stmt = select(models.Group).where(
            models.Group.normalized_name == new_normalized,
            models.Group.parent_id == g.parent_id,  # None → is NULL работает корректно
            models.Group.is_deleted.is_(False),
            models.Group.id != g.id,
        )
        if db.execute(stmt).scalar_one_or_none():
            raise DomainError(status=409, code="NAME_CONFLICT", title="Конфликт названия",
                              detail="Группа с таким названием уже существует в этом разделе")
    g.name = name.strip()
    g.normalized_name = new_normalized
    # US-049 ш.1 (FR-140, LLD §11 group.rename)
    if actor is not None:
        audit_log(db, actor, "group.rename", "group", g.id,
                  details={"name": g.name})
    commit_rights(db)
    return to_out(g)
