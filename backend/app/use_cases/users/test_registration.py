# Тестовая регистрация с выбором роли (НЕ для продуктива; вне LLD — фича стенда).
# Пользователь создаётся штатно при первом запросе (FR-013, provision_user); после
# входа он не имеет ни одной роли (default deny, §3.2) и не видит систему. Здесь
# он может один раз выбрать себе роль из допустимого списка — запись user_roles,
# как делает СА (FR-007). Включается флагом KB_TEST_REGISTRATION=true; на
# продуктиве флаг не задаётся.
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import models
from app.use_cases.errors import DomainError
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.permissions.cache import commit_rights
from app.use_cases.roles.constants import SUPERUSER_ROLE_NAME

# Роли, которые нельзя получить через тестовую регистрацию
FORBIDDEN_ROLE_NAMES = (SUPERUSER_ROLE_NAME,)
# Право, при наличии которого в шаблоне роль не предлагается (сам себе СА)
_PRIV_MANAGE = models.PermissionCode.manage_permissions


def feature_enabled() -> bool:
    return bool(get_settings().test_registration)


def selectable_roles(db: Session) -> list[models.Role]:
    """Допустимые роли: все шаблоны, кроме СА, виртуальной и с manage_permissions."""
    roles = db.execute(
        select(models.Role)
        .where(
            models.Role.is_virtual_all_users.is_(False),
            models.Role.name.notin_(FORBIDDEN_ROLE_NAMES),
        )
        .order_by(models.Role.created_at)
    ).scalars().all()
    return [r for r in roles if not any(p.permission == _PRIV_MANAGE for p in r.permissions)]


def get_offer(db: Session, user: models.User) -> dict:
    """Состояние оффера: флаг, доступен ли выбор, допустимые роли.

    При выключенном флаге список ролей не раскрывается (roles: []).
    Роли читаются запросом (не relationship) — запись могла появиться
    в этой же транзакции/запросе (US-003: СА назначил, пользователь зашёл).
    """
    enabled = feature_enabled()
    return {
        "enabled": enabled,
        # Доступно, пока у пользователя нет ни одной роли (FR-010; дальше — только СА)
        "available": enabled and not user.is_service and not has_roles(db, user.id),
        "user_id": str(user.id),
        "roles": [{"id": str(r.id), "name": r.name} for r in (selectable_roles(db) if enabled else [])],
    }


def has_roles(db: Session, user_id) -> bool:
    """Есть ли у пользователя хотя бы одна роль (user_roles, FR-010)."""
    return db.execute(
        select(models.UserRole.role_id).where(models.UserRole.user_id == user_id).limit(1)
    ).first() is not None


def choose_role(db: Session, user: models.User, role_id: str) -> dict:
    """Одноразовый выбор роли: только при включённом флаге и если ролей ещё нет."""
    if not feature_enabled():
        raise DomainError(
            status=403,
            code="ACCESS_DENIED",
            title="Функция недоступна",
            detail="Тестовая регистрация отключена",
        )
    if user.is_service:
        raise DomainError(
            status=403,
            code="ACCESS_DENIED",
            title="Функция недоступна",
            detail="Сервисная учётная запись не может выбрать роль",
        )
    if user.roles:
        raise DomainError(
            status=409,
            code="DOMAIN_RULE_VIOLATION",
            title="Роль уже назначена",
            detail="Выбор роли доступен один раз; смену роли выполняет СА",
        )
    # Повторная проверка запросом: relationship мог не увидеть запись,
    # созданную в этой же транзакции (гарантия одноразовости выбора)
    if has_roles(db, user.id):
        raise DomainError(
            status=409,
            code="DOMAIN_RULE_VIOLATION",
            title="Роль уже назначена",
            detail="Выбор роли доступен один раз; смену роли выполняет СА",
        )
    try:
        rid = uuid.UUID(role_id)
    except (ValueError, AttributeError, TypeError):
        raise DomainError(
            status=400,
            code="VALIDATION_ERROR",
            title="Ошибка валидации запроса",
            detail="Некорректный идентификатор роли",
        )
    role = db.execute(
        select(models.Role).where(models.Role.id == rid)
    ).scalar_one_or_none()
    if (
        role is None
        or role.is_virtual_all_users
        or role.name in FORBIDDEN_ROLE_NAMES
        or any(p.permission == _PRIV_MANAGE for p in role.permissions)
    ):
        raise DomainError(
            status=400,
            code="VALIDATION_ERROR",
            title="Роль недоступна",
            detail="Эту роль нельзя выбрать при тестовой регистрации",
        )
    db.add(models.UserRole(user_id=user.id, role_id=role.id))
    # Аудит (LLD §11): самостоятельный выбор в рамках тестовой регистрации
    audit_log(db, user, "user.test_registration", "user", user.id,
              details={"role": role.name})
    commit_rights(db)
    return {"user_id": str(user.id), "role": role.name}
