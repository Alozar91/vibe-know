# CRUD матрицы переходов (LLD §12.3 /transition-rules; US-046, FR-069–074).
# Операции СА. is_protected — только чтение; from_status='archived' → 400
# ARCHIVED_SOURCE_RULE_FORBIDDEN; защищённые правила нельзя удалить (FR-073);
# удаление правила статусы существующих материалов не меняет (FR-074).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import validate_permissions
from app.use_cases.errors import (
    DomainError,
    archived_source_rule_forbidden,
    domain_rule_violation,
    not_found,
)
from app.use_cases.lifecycle.available_transitions import rule_out
from app.use_cases.lifecycle.audit import audit_log

VALID_STATUSES = [s.value for s in models.MaterialStatus]


def list_rules(db: Session, is_super: bool) -> list[dict]:
    """Матрица целиком (для UI СА: checkbox + права)."""
    from app.use_cases.common import require_super

    require_super(is_super)
    rules = db.execute(
        select(models.TransitionRule).order_by(
            models.TransitionRule.from_status.is_(None),
            models.TransitionRule.from_status,
            models.TransitionRule.to_status,
        )
    ).scalars().all()
    return [rule_out(r) for r in rules]


def create_rule(
    db: Session, is_super: bool, from_status: str | None, to_status: str, permissions: list[str],
) -> dict:
    """Новое правило матрицы (US-046 шаг 2)."""
    from app.use_cases.common import require_super

    require_super(is_super)
    if from_status == "archived":
        raise archived_source_rule_forbidden()
    for s in filter(None, [from_status, to_status]):
        if s not in VALID_STATUSES:
            raise DomainError(
                status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                detail=f"Неизвестный статус: {s}",
            )
    if to_status is None:
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail="Целевой статус обязателен",
        )
    perms = validate_permissions(permissions)
    dup = db.execute(
        select(models.TransitionRule).where(
            models.TransitionRule.from_status == from_status,
            models.TransitionRule.to_status == to_status,
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise domain_rule_violation(409, "Правило для этого перехода уже существует")
    rule = models.TransitionRule(
        from_status=models.MaterialStatus(from_status) if from_status else None,
        to_status=models.MaterialStatus(to_status),
        is_protected=False,
    )
    for p in set(perms):
        rule.permissions.append(models.TransitionRulePermission(permission=p))
    db.add(rule)
    db.flush()
    audit_log(
        db, None, "transition_matrix.change", "transition_rule", rule.id,
        details={
            "op": "create",
            "from": from_status,
            "to": to_status,
            "permissions": sorted(str(p.value) for p in perms),
        },
    )
    db.commit()
    return rule_out(rule)


def delete_rule(db: Session, is_super: bool, rule_id: str) -> None:
    """Удаление незащищённого правила (US-046 шаг 3; FR-073/074)."""
    from app.use_cases.common import require_super, parse_uuid

    rule = db.execute(
        select(models.TransitionRule).where(models.TransitionRule.id == parse_uuid(rule_id))
    ).scalar_one_or_none()
    if rule is None:
        raise not_found("Правило не найдено")
    if rule.is_protected:
        raise domain_rule_violation(
            409, "Защищённые системные переходы нельзя удалить (FR-073)"
        )
    details = {
        "op": "delete",
        "from": rule.from_status.value if hasattr(rule.from_status, "value") else (str(rule.from_status) if rule.from_status else None),
        "to": rule.to_status.value if hasattr(rule.to_status, "value") else str(rule.to_status),
        "permissions": sorted(
            p.permission.value if hasattr(p.permission, "value") else str(p.permission)
            for p in rule.permissions
        ),
    }
    db.delete(rule)
    audit_log(db, None, "transition_matrix.change", "transition_rule", rule.id, details=details)
    db.commit()


def replace_rule_permissions(
    db: Session, is_super: bool, rule_id: str, permissions: list[str]
) -> dict:
    """Смена прав перехода (US-046 шаг 2): полный список прав — достаточно любого (FR-070)."""
    from app.use_cases.common import require_super, parse_uuid

    require_super(is_super)
    rule = db.execute(
        select(models.TransitionRule).where(models.TransitionRule.id == parse_uuid(rule_id))
    ).scalar_one_or_none()
    if rule is None:
        raise not_found("Правило не найдено")
    perms = validate_permissions(permissions)
    rule.permissions.clear()
    for p in set(perms):
        rule.permissions.append(models.TransitionRulePermission(permission=p))
    db.flush()
    audit_log(
        db, None, "transition_matrix.change", "transition_rule", rule.id,
        details={
            "op": "set_permissions",
            "from": rule.from_status.value if hasattr(rule.from_status, "value") else (str(rule.from_status) if rule.from_status else None),
            "to": rule.to_status.value if hasattr(rule.to_status, "value") else str(rule.to_status),
            "permissions": sorted(str(p.value) for p in perms),
        },
    )
    db.commit()
    return rule_out(rule)
