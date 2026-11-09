# Доступные переходы (LLD §12.3 GET /materials/{id}/transitions, FR-070).
# Для карточки UI: по текущему статусу — правила матрицы; для каждого —
# доступность (права перехода, FR-070/072) и need_cascade (FR-039).
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.permissions.eff import eff_rows, group_chain_ids, has_right


def rule_out(rule: models.TransitionRule) -> dict:
    """Строка матрицы для UI/СА: from '*' для NULL; права списком (FR-070)."""
    fs = rule.from_status
    fs_v = fs.value if hasattr(fs, "value") else (str(fs) if fs else None)
    ts = rule.to_status
    ts_v = ts.value if hasattr(ts, "value") else str(ts)
    return {
        "id": str(rule.id),
        "from_status": fs_v,  # None = «*»
        "to_status": ts_v,
        "is_protected": rule.is_protected,
        "permissions": sorted(
            p.permission.value if hasattr(p.permission, "value") else str(p.permission)
            for p in rule.permissions
        ),
    }


def available_transitions(db: Session, user, material) -> list[dict]:
    """Переходы из текущего статуса с признаком доступности и need_cascade."""
    from_v = material.status.value if hasattr(material.status, "value") else str(material.status)
    rules = db.execute(
        select(models.TransitionRule).where(
            (models.TransitionRule.from_status == from_v)
            | (models.TransitionRule.from_status.is_(None))
        )
    ).scalars().all()
    eff = eff_rows(db, user.user_id, group_chain_ids(db, material.group.path), material_id=material.id)

    children_count = db.execute(
        select(func.count())
        .select_from(models.Material)
        .where(models.Material.master_id == material.id, models.Material.is_deleted.is_(False))
    ).scalar_one()

    out = []
    for rule in rules:
        perms = [
            p.permission.value if hasattr(p.permission, "value") else str(p.permission)
            for p in rule.permissions
        ]
        allowed = user.is_super or (bool(perms) and any(has_right(eff, p) for p in perms))
        out.append(
            {
                **rule_out(rule),
                "allowed": allowed,
                "need_cascade": children_count > 0,
                "children_count": children_count,
            }
        )
    # Сначала точные правила (from_status не NULL), затем «*»
    return sorted(out, key=lambda r: (r["from_status"] is not None, r["to_status"]))
