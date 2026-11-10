# /me — профиль из токена (LLD §12.3, FR-151). Транспорт: без бизнес-логики.
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases.users.test_registration import choose_role, get_offer

router = APIRouter(tags=["me"])


@router.get("/me")
def me(user: CurrentUserDep, db: Session = Depends(get_db)) -> dict:
    """Профиль аутентифицированного участника (FR-151: минимум ПДн)."""
    # Имена ролей (FR-007) — запросом (не relationship): запись могла появиться
    # в этой же транзакции; SPA показывает роль в шапке и оффер тестовой
    # регистрации, пока ролей нет (default deny, §3.2)
    from sqlalchemy import select

    from app.db import models

    role_names = db.execute(
        select(models.Role.name)
        .join(models.UserRole, models.UserRole.role_id == models.Role.id)
        .where(models.UserRole.user_id == user.user_id)
        .order_by(models.Role.created_at)
    ).scalars().all()
    return {
        "id": str(user.user_id),
        "display_name": user.display_name,
        "is_service": user.is_service,
        "is_super": user.is_super,
        "roles": list(role_names),
    }


class TestRoleIn(BaseModel):
    role_id: str = Field(min_length=1, max_length=64)


@router.get("/me/test-registration")
def test_registration_offer(user: CurrentUserDep, db: Session = Depends(get_db)) -> dict:
    """Состояние тестовой регистрации (НЕ для продуктива; флаг KB_TEST_REGISTRATION)."""
    return get_offer(db, user.db_user)


@router.post("/me/test-registration", status_code=200)
def test_registration_choose(user: CurrentUserDep, body: TestRoleIn, db: Session = Depends(get_db)) -> dict:
    """Одноразовый выбор роли при тестовой регистрации (вне LLD — фича стенда)."""
    return choose_role(db, user.db_user, body.role_id)
