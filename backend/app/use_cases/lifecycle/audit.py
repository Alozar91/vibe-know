# Аудит (LLD §11, FR-140–143): append-only записи.
# Этап 5 создаёт записи; просмотр/экспорт/очистка — этап 10 (план §Состав).
from sqlalchemy.orm import Session

from app.db import models


def audit_log(
    db: Session,
    user,
    action: str,
    object_type: str,
    object_id,
    details: dict | None = None,
) -> None:
    """Запись аудита: кто (actor), когда (occurred_at — server_default), что, над чем.

    Системные события (конвейер файлов, этап 6) — user=None, is_service=True.
    """
    db.add(
        models.AuditEntry(
            actor_user_id=getattr(user, "user_id", None),
            actor_is_service=bool(getattr(user, "is_service", False)),
            action=action,
            object_type=object_type,
            object_id=object_id,
            details=details or {},
        )
    )
