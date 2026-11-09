# Назначение ролей — транспорт (LLD §12.3). Логика: use_cases.user_roles.
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases import user_roles as user_roles_uc

router = APIRouter(tags=["roles"])


@router.put("/users/{user_id}/roles/{role_id}", status_code=204)
async def assign_role(
    user: CurrentUserDep, user_id: str, role_id: str, db: Session = Depends(get_db)
) -> None:
    """Назначение роли — служебный раздел СА (FR-007, US-003 шаг 2)."""
    user_roles_uc.assign_role(db, user.is_super, user_id, role_id)


@router.delete("/users/{user_id}/roles/{role_id}", status_code=204)
async def revoke_role(
    user: CurrentUserDep, user_id: str, role_id: str, db: Session = Depends(get_db)
) -> None:
    """Снятие роли (FR-007, FR-010) — СА."""
    user_roles_uc.revoke_role(db, user.is_super, user_id, role_id)
