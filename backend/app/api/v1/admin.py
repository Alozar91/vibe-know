# Admin — транспорт СА-контура (LLD §12.3: §11 аудит, §2.5 настройки, FR-012, NFR-014).
#   GET  /audit                  — журнал (пагинация, фильтры) — FR-140
#   GET  /audit/export           — выгрузка NDJSON (фиксируется audit.export) — FR-143
#   GET/PUT /settings[/{key}]    — реестр параметров — NFR-020, US-048
#   GET  /service-tasks, POST /service-tasks/{id}:close — задачи СА — FR-012
#   GET  /tasks                  — состояния system_tasks — NFR-014
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases import admin
from app.use_cases.admin.service_tasks import (
    close_service_task,
    list_service_tasks,
    list_system_tasks,
)
from app.use_cases.admin.settings import list_settings, update_setting
from app.use_cases.audit.list_audit import iter_audit_ndjson, list_audit

router = APIRouter(tags=["admin"])


def _require(is_super: bool) -> None:
    from app.use_cases.errors import access_denied

    if not is_super:
        raise access_denied("Требуются права системного администратора")


# --- Аудит (US-049, FR-140–143) ---


@router.get("/audit")
def audit_ep(
    user: CurrentUserDep,
    page: int = 1,
    per_page: int = Query(50, le=200),
    action: str | None = None,
    object_type: str | None = None,
    actor_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    _require(user.is_super)
    return list_audit(db, True, page=page, per_page=per_page, action=action,
                      object_type=object_type, actor_id=actor_id,
                      date_from=date_from, date_to=date_to)


@router.get("/audit/export")
def audit_export_ep(
    user: CurrentUserDep,
    action: str | None = None,
    object_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
):
    """NDJSON-поток (FR-143); выгрузка фиксируется в аудите до выдачи тела."""
    _require(user.is_super)
    gen = iter_audit_ndjson(db, user.db_user, action=action, object_type=object_type,
                            date_from=date_from, date_to=date_to)
    return StreamingResponse(
        gen,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="audit-export.ndjson"'},
    )


# --- Настройки (US-048, NFR-020) ---


class SettingIn(BaseModel):
    value: object


@router.get("/settings")
def settings_ep(user: CurrentUserDep, db: Session = Depends(get_db)) -> list[dict]:
    _require(user.is_super)
    return list_settings(db, True)


@router.put("/settings/{key}")
def update_setting_ep(
    key: str, body: SettingIn, user: CurrentUserDep, db: Session = Depends(get_db)
) -> dict:
    _require(user.is_super)
    return update_setting(db, user.db_user, True, key, body.value)


# --- Служебные задачи (FR-012, US-004) и /tasks (NFR-014) ---


@router.get("/service-tasks")
def service_tasks_ep(
    user: CurrentUserDep, all: bool = False, db: Session = Depends(get_db)
) -> list[dict]:
    _require(user.is_super)
    return list_service_tasks(db, True, all=all)


@router.post("/service-tasks/{task_id}:close")
def close_service_task_ep(
    task_id: str, user: CurrentUserDep, db: Session = Depends(get_db)
) -> dict:
    _require(user.is_super)
    return close_service_task(db, user.db_user, True, task_id)


@router.get("/tasks")
def tasks_ep(
    user: CurrentUserDep, limit: int = Query(100, le=500), db: Session = Depends(get_db)
) -> dict:
    _require(user.is_super)
    return list_system_tasks(db, True, limit=limit)
