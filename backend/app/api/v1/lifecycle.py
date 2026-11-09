# Жизненный цикл — транспорт (LLD §12.3). Логика: use_cases/lifecycle/*.
# Переходы: POST /materials/{id}/transitions {to_status, confirm_cascade};
# GET /materials/{id}/transitions — доступные переходы;
# GET /materials/{id}/status-log — журнал статусов;
# /transition-rules — CRUD матрицы (СА); is_protected — только чтение.
import json

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db

router = APIRouter(tags=["lifecycle"])
rules_router = APIRouter(tags=["lifecycle"])


class TransitionIn(BaseModel):
    to_status: str
    confirm_cascade: bool = False


class TransitionRuleIn(BaseModel):
    from_status: str | None = None
    to_status: str
    permissions: list[str] = Field(default_factory=list)


class TransitionRulePatch(BaseModel):
    permissions: list[str] = Field(default_factory=list)


def _json(obj) -> Response:
    return Response(
        content=json.dumps(obj, ensure_ascii=False), media_type="application/json"
    )


@router.post("/materials/{material_id}/transitions")
async def transition_ep(
    user: CurrentUserDep, material_id: str, body: TransitionIn,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
):
    """Переход статуса (§4.1): валидаторы + фиксация; ETag = новая версия."""
    from app.use_cases.lifecycle.transition import transition

    result = transition(db, user, material_id, body.to_status, if_match, body.confirm_cascade)
    return Response(
        content=json.dumps(result, ensure_ascii=False),
        media_type="application/json",
        headers={"ETag": f'"{result["version"]}"'},
    )


@router.get("/materials/{material_id}/transitions")
async def available_transitions_ep(
    user: CurrentUserDep, material_id: str, db: Session = Depends(get_db),
):
    """Доступные переходы из текущего статуса (FR-070): правило, права, доступность."""
    from app.use_cases.materials.get_material import get_material_or_404
    from app.use_cases.lifecycle.available_transitions import available_transitions

    m = get_material_or_404(db, user, material_id)
    return _json(available_transitions(db, user, m))


@router.get("/materials/{material_id}/status-log")
async def status_log_ep(
    user: CurrentUserDep, material_id: str, db: Session = Depends(get_db),
):
    """Журнал статусов (FR-075); видимость материала обязательна (§12.3)."""
    from app.use_cases.lifecycle.status_log import list_status_log

    return _json(list_status_log(db, user, material_id))


@rules_router.get("/transition-rules")
async def list_rules_ep(user: CurrentUserDep, db: Session = Depends(get_db)):
    """Матрица переходов (FR-070) — СА; is_protected только для чтения."""
    from app.use_cases.lifecycle.rules_crud import list_rules

    return _json(list_rules(db, user.is_super))


@rules_router.post("/transition-rules")
async def create_rule_ep(user: CurrentUserDep, body: TransitionRuleIn, db: Session = Depends(get_db)):
    """Новое правило (US-046): from_status='archived' → 400 ARCHIVED_SOURCE_RULE_FORBIDDEN."""
    from app.use_cases.lifecycle.rules_crud import create_rule

    return _json(create_rule(db, user.is_super, body.from_status, body.to_status, body.permissions))


@rules_router.patch("/transition-rules/{rule_id}")
async def patch_rule_ep(
    user: CurrentUserDep, rule_id: str, body: TransitionRulePatch, db: Session = Depends(get_db),
):
    """Смена прав перехода (US-046 шаг 2): достаточно любого из списка (FR-070)."""
    from app.use_cases.lifecycle.rules_crud import replace_rule_permissions

    return _json(replace_rule_permissions(db, user.is_super, rule_id, body.permissions))


@rules_router.delete("/transition-rules/{rule_id}")
async def delete_rule_ep(user: CurrentUserDep, rule_id: str, db: Session = Depends(get_db)):
    """Удаление незащищённого правила (FR-073/074): 204."""
    from app.use_cases.lifecycle.rules_crud import delete_rule

    delete_rule(db, user.is_super, rule_id)
    return Response(status_code=204)
