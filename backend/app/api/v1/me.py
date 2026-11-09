# /me — профиль из токена (LLD §12.3, FR-151).
from fastapi import APIRouter

from app.api.deps import CurrentUserDep

router = APIRouter(tags=["me"])


@router.get("/me")
async def me(user: CurrentUserDep) -> dict:
    """Профиль аутентифицированного участника (FR-151: минимум ПДн)."""
    return {
        "id": str(user.user_id),
        "display_name": user.display_name,
        "is_service": user.is_service,
        "is_super": user.is_super,
    }
