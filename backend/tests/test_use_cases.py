# Юнит-тесты use-cases: бизнес-логика без HTTP (доменные ошибки, клонирование, деактивация).
"""Слой use-cases: чистая бизнес-логика этапа 2 (сценарий = файл)."""
import pytest
from sqlalchemy import select

from app.db import models
from app.use_cases.errors import DomainError
from app.use_cases.roles.assign_role import assign_role
from app.use_cases.roles.clone_role import clone_role
from app.use_cases.roles.create_role import create_role
from app.use_cases.roles.revoke_role import revoke_role
from app.use_cases.roles.update_role import update_role
from app.use_cases.users.deactivate_user import deactivate_user


def test_create_role_requires_super(db):
    """FR-104: не-СА не создаёт шаблоны."""
    with pytest.raises(DomainError) as e:
        create_role(db, is_super=False, name="x", permissions=[])
    assert e.value.status == 403 and e.value.code == "ACCESS_DENIED"


def test_create_role_unknown_permission(db):
    """Каталог прав FR-106: неизвестный код — 400 VALIDATION_ERROR."""
    with pytest.raises(DomainError) as e:
        create_role(db, is_super=True, name="x", permissions=["нет такого"])
    assert e.value.status == 400 and e.value.code == "VALIDATION_ERROR"


def test_clone_role_copies_permissions(db):
    """FR-105: клон = копия набора прав; исходник не меняется."""
    src = next(x for x in db.execute(select(models.Role)).scalars() if x.name == "Автор")
    out = clone_role(db, is_super=True, role_id=str(src.id))
    assert out["permissions"] == ["create", "delete", "edit", "view"]
    assert out["name"] == "Автор (копия)"
    assert out["id"] != str(src.id)


def test_update_missing_role_404(db):
    """Несуществующая роль — RESOURCE_NOT_FOUND."""
    with pytest.raises(DomainError) as e:
        update_role(
            db, is_super=True,
            role_id="00000000-0000-0000-0000-000000000000", name=None, permissions=[],
        )
    assert e.value.code == "RESOURCE_NOT_FOUND"


def test_deactivate_self_forbidden(db):
    """Этап 2: СА не деактивирует себя."""
    from tests.conftest import _make_principal

    principal = _make_principal(db, "СА сам", is_super=True)
    with pytest.raises(DomainError) as e:
        deactivate_user(db, actor=principal.db_user, is_super=True, user_id=str(principal.user_id))
    assert e.value.status == 409 and e.value.code == "SELF_DEACTIVATION_FORBIDDEN"


def test_revoke_unassigned_role_404(db):
    """Снятие неназначенной роли — 404."""
    from tests.conftest import _make_principal

    principal = _make_principal(db, "Юзер без ролей")
    reader = db.execute(select(models.Role).where(models.Role.name == "Читатель")).scalar_one()
    with pytest.raises(DomainError) as e:
        revoke_role(db, is_super=True, user_id=str(principal.user_id), role_id=str(reader.id))
    assert e.value.status == 404


def test_assign_role_idempotent(db):
    """FR-010: повторное назначение не создаёт дубликат."""
    from tests.conftest import _make_principal

    principal = _make_principal(db, "Юзер для роли")
    reader = db.execute(select(models.Role).where(models.Role.name == "Читатель")).scalar_one()
    assign_role(db, is_super=True, user_id=str(principal.user_id), role_id=str(reader.id))
    assign_role(db, is_super=True, user_id=str(principal.user_id), role_id=str(reader.id))
    links = db.execute(
        select(models.UserRole).where(models.UserRole.user_id == principal.user_id)
    ).scalars().all()
    assert len(links) == 1


def test_list_users_clamps_per_page(db):
    """FR-131: per_page=<1 и >200 зажимается в границы; page<1 → 1."""
    from tests.conftest import _make_principal
    from app.use_cases.users.list_users import list_users

    _make_principal(db, "Юзер пагинации")
    p = list_users(db, is_super=True, page=0, per_page=0)
    assert (p.page, p.per_page) == (1, 1)
    p2 = list_users(db, is_super=True, page=1, per_page=9999)
    assert p2.per_page == 200


def test_virtual_role_not_renamable(db):
    """FR-009: «Все пользователи» не редактируется ни по составу, ни по имени."""
    from app.use_cases.errors import domain_rule_violation as drv  # noqa
    from app.use_cases.roles.constants import VIRTUAL_ALL_USERS_NAME

    virtual = db.execute(
        select(models.Role).where(models.Role.is_virtual_all_users.is_(True))
    ).scalar_one()
    with pytest.raises(DomainError) as e1:
        update_role(db, is_super=True, role_id=str(virtual.id), name="Другое", permissions=None)
    with pytest.raises(DomainError) as e2:
        update_role(db, is_super=True, role_id=str(virtual.id), name=None, permissions=[])
    assert e1.value.status == e2.value.status == 409
