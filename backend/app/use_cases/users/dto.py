# DTO пользователей (FR-151: минимум ПДн) — общие для сценариев ресурса.
from dataclasses import dataclass, field

from app.db import models


@dataclass
class UserOut:
    id: str
    display_name: str
    email_cache: str | None
    is_deactivated: bool
    is_service: bool
    roles: list[str] = field(default_factory=list)


def to_out(u: models.User) -> UserOut:
    return UserOut(
        id=str(u.id),
        display_name=u.display_name,
        email_cache=u.email_cache,
        is_deactivated=u.is_deactivated,
        is_service=u.is_service,
        roles=[ur.role.name for ur in u.roles],
    )
