# Use-case: provisioning пользователя при первом запросе (HLD §6.1, FR-013) + email_cache (16.1-119).
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


def upsert_user_from_token(db: Session, info: dict[str, Any]) -> models.User:
    """Находит users по keycloak_id или создаёт запись; обновляет email_cache при отличии.

    Сервисная УЗ: токен client credentials — без сессии (LLD §10, FR-013).
    Introspection Keycloak не возвращает session_state; идентификатор сессии — claim sid.
    """
    user = db.execute(
        select(models.User).where(models.User.keycloak_id == info["sub"])
    ).scalar_one_or_none()
    if user is None:
        user = models.User(
            keycloak_id=info["sub"],
            display_name=info.get("name") or info.get("preferred_username") or info["sub"],
            email_cache=info.get("email"),
            is_service=not bool(info.get("sid")),
        )
        db.add(user)
        db.flush()
    elif user.email_cache != info.get("email"):
        user.email_cache = info.get("email")
    return user
