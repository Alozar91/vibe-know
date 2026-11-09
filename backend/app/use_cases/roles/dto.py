# DTO ролей — общие для сценариев ресурса.
from app.db import models


def to_out(r: models.Role) -> dict:
    perms = sorted(
        p.permission.value if hasattr(p.permission, "value") else str(p.permission)
        for p in r.permissions
    )
    return {
        "id": str(r.id),
        "name": r.name,
        "is_virtual_all_users": r.is_virtual_all_users,
        "permissions": perms,
    }
