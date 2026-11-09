# Сценарии аутентификации/provisioning (LLD §10, HLD §6.1).
# Чистая логика: introspection как HTTP-клиент вынесен сюда; FastAPI-слой только извлекает токен.
import base64
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import models
from app.use_cases.errors import DomainError


def introspect_token(token: str) -> dict[str, Any]:
    """POST introspection (LLD §10): Basic-auth api-клиента, таймаут 2 с, 1 повтор.

    Бросает DomainError 401 при любом сбое/active=false (fail-closed).
    """
    s = get_settings()
    auth = _basic_auth_header(s.oidc_client_id, s.oidc_client_secret)
    try:
        with httpx.Client(timeout=2.0) as client:
            r = client.post(s.oidc_introspection_url, data={"token": token}, headers=auth)
            if r.status_code != 200:
                raise DomainError(
                    status=401, code="UNAUTHENTICATED", title="Требуется аутентификация",
                    detail="Токен не принят сервисом аутентификации",
                )
            info = r.json()
    except httpx.HTTPError:
        # 1 повтор при сетевом сбое (LLD §10)
        try:
            with httpx.Client(timeout=2.0) as client:
                r = client.post(s.oidc_introspection_url, data={"token": token}, headers=auth)
                if r.status_code != 200:
                    raise DomainError(
                        status=401, code="UNAUTHENTICATED", title="Требуется аутентификация",
                        detail="Токен не принят сервисом аутентификации",
                    )
                info = r.json()
        except httpx.HTTPError:
            raise DomainError(
                status=401, code="UNAUTHENTICATED", title="Требуется аутентификация",
                detail="Сервис аутентификации недоступен",
            )

    if not info.get("active", False):
        raise DomainError(
            status=401, code="UNAUTHENTICATED", title="Требуется аутентификация",
            detail="Токен недействителен",
        )
    return info


def _basic_auth_header(client_id: str, client_secret: str) -> dict[str, str]:
    raw = f"{client_id}:{client_secret}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def upsert_user_from_token(db: Session, info: dict[str, Any]) -> models.User:
    """Provisioning при первом запросе (§6.1 HLD) + email_cache (16.1-119)."""
    user = db.execute(
        select(models.User).where(models.User.keycloak_id == info["sub"])
    ).scalar_one_or_none()
    if user is None:
        # Сервисная УЗ: токен client credentials — без сессии (LLD §10, FR-013).
        # Introspection Keycloak не возвращает session_state; идентификатор сессии — claim sid.
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


def ensure_active(user: models.User) -> None:
    """FR-011: деактивированный — токены не действуют (fail-closed, US-001 A2)."""
    if user.is_deactivated:
        raise DomainError(
            status=401, code="UNAUTHENTICATED", title="Требуется аутентификация",
            detail="Учётная запись деактивирована",
        )


def is_super(db: Session, user: models.User) -> bool:
    """FR-104: флаг сессии — принадлежность шаблону «Системный администратор» (LLD §3.2)."""
    admin_role = db.execute(
        select(models.Role).where(models.Role.name == "Системный администратор")
    ).scalar_one_or_none()
    if admin_role is None:
        return False
    link = db.execute(
        select(models.UserRole).where(
            models.UserRole.user_id == user.id, models.UserRole.role_id == admin_role.id
        )
    ).first()
    return link is not None
