# Аутентификация: Token Introspection на каждый запрос (LLD §10, FR-011, HLD §6.1).
# fail-closed: любой сбой/active=false → 401; таймаут 2 с, 1 повтор.
# Provisioning: пользователь создается при первом запросе (§6.1 HLD, FR-013 для сервисных УЗ).
import base64
from typing import Annotated, Any

import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import models
from app.db.engine import get_db


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


def _basic_auth_header(client_id: str, client_secret: str) -> dict[str, str]:
    raw = f"{client_id}:{client_secret}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _introspect(token: str) -> dict[str, Any]:
    """POST introspection (LLD §10): Basic-auth api-клиента, таймаут 2 с, 1 повтор."""
    s = get_settings()
    try:
        with httpx.Client(timeout=2.0) as client:
            r = client.post(
                s.oidc_introspection_url,
                data={"token": token},
                headers=_basic_auth_header(s.oidc_client_id, s.oidc_client_secret),
            )
            if r.status_code != 200:
                raise HTTPException(status_code=401, detail="Требуется аутентификация")
            info = r.json()
    except httpx.HTTPError:
        # 1 повтор при сетевом сбое (LLD §10)
        try:
            with httpx.Client(timeout=2.0) as client:
                r = client.post(
                    s.oidc_introspection_url,
                    data={"token": token},
                    headers=_basic_auth_header(s.oidc_client_id, s.oidc_client_secret),
                )
                if r.status_code != 200:
                    raise HTTPException(status_code=401, detail="Требуется аутентификация")
                info = r.json()
        except httpx.HTTPError:
            raise HTTPException(status_code=401, detail="Сервис аутентификации недоступен")

    if not info.get("active", False):
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    return info


def _provision_user(db: Session, info: dict[str, Any]) -> models.User:
    """При первом запросе — создание users (§6.1 HLD; email_cache — 16.1-119)."""
    keycloak_id = info["sub"]
    display_name = info.get("name") or info.get("preferred_username") or keycloak_id
    # Сервисная УЗ: токен client credentials — без сессии (LLD §10, FR-013).
    # Introspection Keycloak не возвращает session_state; идентификатор сессии — claim sid.
    is_service = not bool(info.get("sid"))
    user = models.User(
        keycloak_id=keycloak_id,
        display_name=display_name,
        email_cache=info.get("email"),  # кэш адреса истины (16.1-119)
        is_service=is_service,
    )
    db.add(user)
    db.flush()
    return user


def _update_email_cache(db: Session, user: models.User, email: str | None) -> None:
    """Обновление email_cache при отличии (16.1-119, LLD §10)."""
    if user.email_cache != email:
        user.email_cache = email


def _is_super(db: Session, user: models.User) -> bool:
    """FR-104: флаг сессии — принадлежность шаблону «Системный администратор» (LLD §3.2)."""
    admin_role = db.execute(
        select(models.Role).where(models.Role.name == "Системный администратор")
    ).scalar_one_or_none()
    if admin_role is None:
        return False
    stmt = select(models.UserRole).where(
        models.UserRole.user_id == user.id, models.UserRole.role_id == admin_role.id
    )
    return db.execute(stmt).first() is not None


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> CurrentUser:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    token = auth.removeprefix("Bearer ").strip()

    info = _introspect(token)

    user = db.execute(
        select(models.User).where(models.User.keycloak_id == info["sub"])
    ).scalar_one_or_none()

    if user is None:
        user = _provision_user(db, info)
    else:
        _update_email_cache(db, user, info.get("email"))

    if user.is_deactivated:
        # FR-011: деактивированный — токены не действуют (fail-closed, US-001 A2)
        raise HTTPException(status_code=401, detail="Учётная запись деактивирована")

    db.commit()
    return CurrentUser(user, info, _is_super(db, user))


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
