# Юнит-тесты use-cases: бизнес-логика без HTTP (доменные ошибки, клонирование, деактивация).
"""Слой use-cases: чистая бизнес-логика этапа 2."""
import pytest

from app.db import models
from app.use_cases import roles as roles_uc, users as users_uc, user_roles as user_roles_uc
from app.use_cases.errors import DomainError


def test_create_role_requires_super(db):
    """FR-104: не-СА не создаёт шаблоны."""
    with pytest.raises(DomainError) as e:
        roles_uc.create_role(db, is_super=False, name="x", permissions=[])
    assert e.value.status == 403 and e.value.code == "ACCESS_DENIED"


def test_create_role_unknown_permission(db):
    """Каталог прав FR-106: неизвестный код — 400 VALIDATION_ERROR."""
    with pytest.raises(DomainError) as e:
        roles_uc.create_role(db, is_super=True, name="x", permissions=["нет такого"])
    assert e.value.status == 400 and e.value.code == "VALIDATION_ERROR"


def test_clone_role_copies_permissions(db):
    """FR-105: клон = копия набора прав; исходник не меняется."""
    src = next(x for x in db.execute(__import__("sqlalchemy").select(models.Role)).scalars() if x.name == "Автор")
    out = roles_uc.clone_role(db, is_super=True, role_id=str(src.id))
    assert out["permissions"] == ["create", "delete", "edit", "view"]
    assert out["name"] == "Автор (копия)"
    assert out["id"] != str(src.id)


def test_virtual_role_no_permissions(db):
    """FR-009: «Все пользователи» — без состава прав."""
    with pytest.raises(DomainError) as e:
        roles_uc.update_role(db, is_super=True, role_id="00000000-0000-0000-0000-000000000000", name=None, permissions=[])
    assert e.value.code == "RESOURCE_NOT_FOUND"  # сначала поиск роли


def test_deactivate_self_forbidden(db):
    """Этап 2: СА не деактивирует себя."""
    from tests.conftest import _make_principal

    principal = _make_principal(db, "СА сам", is_super=True)
    with pytest.raises(DomainError) as e:
        users_uc.deactivate_user(db, actor=principal.db_user, is_super=True, user_id=str(principal.user_id))
    assert e.value.status == 409 and e.value.code == "SELF_DEACTIVATION_FORBIDDEN"


def test_revoke_unassigned_role_404(db):
    """Снятие неназначенной роли — 404."""
    from tests.conftest import _make_principal
    from sqlalchemy import select

    principal = _make_principal(db, "Юзер без ролей")
    reader = db.execute(select(models.Role).where(models.Role.name == "Читатель")).scalar_one()
    with pytest.raises(DomainError) as e:
        user_roles_uc.revoke_role(db, is_super=True, user_id=str(principal.user_id), role_id=str(reader.id))
    assert e.value.status == 404
