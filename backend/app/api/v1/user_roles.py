# Назначение ролей — транспорт (LLD §12.3). Логика: use_cases/roles/*.
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases.roles.assign_role import assign_role
from app.use_cases.roles.revoke_role import revoke_role

router = APIRouter(tags=["roles"])


@router.put("/users/{user_id}/roles/{role_id}", status_code=204)
async def assign_role_ep(
    user: CurrentUserDep, user_id: str, role_id: str, db: Session = Depends(get_db)
) -> None:
    """Назначение роли — служебный раздел СА (FR-007, US-003 шаг 2)."""
    from app.use_cases.roles.assign_role import assign_role as uc

    uc(db, user.is_super, user_id, role_id, actor=user)


@router.delete("/users/{user_id}/roles/{role_id}", status_code=204)
async def revoke_role_ep(
    user: CurrentUserDep, user_id: str, role_id: str, db: Session = Depends(get_db)
) -> None:
    """Снятие роли (FR-007, FR-010) — СА."""
    from app.use_cases.roles.revoke_role import revoke_role as uc

    uc(db, user.is_super, user_id, role_id, actor=user)
