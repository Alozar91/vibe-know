# Use-case: удаление шаблона роли (FR-008) — только СА.
from sqlalchemy.orm import Session

from app.use_cases.common import get_role_or_404, require_super
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.permissions.cache import commit_rights


def delete_role(db: Session, is_super: bool, role_id: str, actor=None) -> None:
    require_super(is_super)
    role = get_role_or_404(db, role_id)
    name = role.name
    rid = role.id
    db.delete(role)
    # US-049 ш.1 (FR-140, LLD §11 role.delete): до commit_rights
    if actor is not None:
        audit_log(db, actor, "role.delete", "role", rid, details={"name": name})
    commit_rights(db)
