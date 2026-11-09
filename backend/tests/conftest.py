# Фикстуры тестов: общая in-memory БД + подмена аутентификации (интроспекция не вызывается).
# Use-cases тестируются сквозь API; интроспекция подменена на уровне get_current_user.
import os

os.environ.setdefault("KB_DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import models
from app.db.base import Base
from app.api.deps import CurrentUser, get_current_user
from app.db.engine import get_db


@pytest.fixture()
def db():
    """Общий in-memory engine: и фикстуры, и приложение работают с одной БД."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    _seed_roles(session)

    from app.main import app

    def override_get_db():
        # Одна сессия на весь тест: эндпоинты сами делают commit при изменениях
        yield session

    app.dependency_overrides[get_db] = override_get_db
    yield session
    app.dependency_overrides.pop(get_db, None)
    session.close()


def _seed_roles(db):
    """Сид шаблонов ролей, как в миграции 0002 (LLD §2.6)."""
    r = {
        "Читатель": ["view"],
        "Автор": ["view", "create", "edit", "delete"],
        "Рецензент": ["view", "review"],
        "Публикатор": ["view", "publish", "archive"],
    }
    for name, perms in r.items():
        role = models.Role(name=name)
        for p in perms:
            role.permissions.append(models.RolePermission(permission=models.PermissionCode(p)))
        db.add(role)
    db.add(models.Role(name="Системный администратор"))
    db.add(models.Role(name="Все пользователи", is_virtual_all_users=True))
    db.commit()


def _make_principal(db, name="Иванов Иван", is_super=False, is_service=False):
    user = models.User(keycloak_id=f"kc-{name}", display_name=name, is_service=is_service)
    db.add(user)
    db.commit()
    token_info = {"sub": user.keycloak_id, "active": True}
    return CurrentUser(user, token_info, is_super)


@pytest.fixture()
def client(db):
    """TestClient с подменой текущего пользователя (по умолчанию — СА)."""
    principal = _make_principal(db, "Тестовый СА", is_super=True)

    def override():
        return principal

    from app.main import app

    app.dependency_overrides[get_current_user] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def as_user(db):
    """Фабрика клиентов от имени заданного пользователя."""
    from app.main import app

    def _client(name="Рядовой пользователь", is_super=False):
        principal = _make_principal(db, name, is_super=is_super)

        def override():
            return principal

        app.dependency_overrides[get_current_user] = override
        return TestClient(app)

    yield _client
    app.dependency_overrides.pop(get_current_user, None)
