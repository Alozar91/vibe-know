# Use-case: удаление шаблона роли (FR-008) — только СА.
from sqlalchemy.orm import Session

from app.use_cases.common import get_role_or_404, require_super
from app.use_cases.permissions.cache import commit_rights


def delete_role(db: Session, is_super: bool, role_id: str) -> None:
    require_super(is_super)
    role = get_role_or_404(db, role_id)
    db.delete(role)
    commit_rights(db)
