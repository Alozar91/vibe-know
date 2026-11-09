# Use-case: карточка пользователя (FR-006) — только СА.
from sqlalchemy.orm import Session

from app.use_cases.common import get_user_or_404, require_super
from app.use_cases.users.dto import UserOut, to_out


def get_user(db: Session, is_super: bool, user_id: str) -> UserOut:
    require_super(is_super)
    return to_out(get_user_or_404(db, user_id))
