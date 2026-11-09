# Аутентификация — транспортный слой (LLD §10, FR-011, HLD §6.1).
# Извлекает Bearer-токен; introspection/provisioning — в use_cases.auth.
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import models
from app.db.engine import get_db
from app.use_cases import auth as auth_uc
from app.use_cases.errors import DomainError


class CurrentUser:
    """Аутентифицированный участник запроса (из introspection + users)."""

    def __init__(self, db_user: models.User, token_info: dict[str, Any], is_super: bool):
        self.db_user = db_user
        self.token_info = token_info
        self.is_super = is_super  # FR-104: принадлежность шаблону «Системный администратор»
        self.keycloak_id: str = db_user.keycloak_id
        self.display_name: str = db_user.display_name
        self.is_service: bool = db_user.is_service

    @property
    def user_id(self):
        return self.db_user.id


def _current_user(db: Session, token: str) -> CurrentUser:
    """Сценарий входа запроса: introspection → provisioning → проверки → флаг СА."""
    info = auth_uc.introspect_token(token)
    user = auth_uc.upsert_user_from_token(db, info)
    auth_uc.ensure_active(user)
    db.commit()
    return CurrentUser(user, info, auth_uc.is_super(db, user))


async def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise DomainError(
            status=401, code="UNAUTHENTICATED", title="Требуется аутентификация",
            detail="Отсутствует Bearer-токен",
        )
    return _current_user(db, auth.removeprefix("Bearer ").strip())


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
