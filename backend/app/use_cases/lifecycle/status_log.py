# Журнал статусов (LLD §2.2, FR-075): запись при каждом переходе.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.errors import not_found


def write_status_log(db: Session, user, material, from_status: str, to_status: str) -> None:
    """Запись журнала: кто, когда, из какого статуса в какой (US-015 шаг 3)."""
    db.add(
        models.StatusLog(
            material_id=material.id,
            from_status=from_status,  # строка или None; enum-значения — в вызывателе
            to_status=to_status,
            user_id=user.user_id,
        )
    )


def list_status_log(db: Session, user, material_id: str) -> list[dict]:
    """Лента журнала статусов материала; видимость материала обязательна (§12.3).
    Хронологический порядок (ASC): ранние переходы — первыми (FR-075)."""
    from app.use_cases.materials.get_material import get_material_or_404

    m = get_material_or_404(db, user, material_id)
    rows = db.execute(
        select(models.StatusLog)
        .where(models.StatusLog.material_id == m.id)
        .order_by(models.StatusLog.created_at.asc(), models.StatusLog.id.asc())
    ).scalars().all()
    out = []
    for r in rows:
        u = db.execute(
            select(models.User.display_name).where(models.User.id == r.user_id)
        ).scalar_one_or_none()
        fs = r.from_status.value if hasattr(r.from_status, "value") else (str(r.from_status) if r.from_status else None)
        ts = r.to_status.value if hasattr(r.to_status, "value") else str(r.to_status)
        out.append(
            {
                "from_status": fs,
                "to_status": ts,
                "user_id": str(r.user_id),
                "user_display_name": u or "?",
                "created_at": r.created_at.isoformat(),
            }
        )
    return out
