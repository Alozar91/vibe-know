# RAG — транспорт СА-контура (RAG_DESIGN §3, §8-1).
#   GET    /admin/rag/chunkers               — реестр чанкеров (для UI)
#   GET    /admin/rag/groups/{id}/config     — явный + effective конфиг
#   PUT    /admin/rag/groups/{id}/config     — создать/обновить (валидация реестром)
#   DELETE /admin/rag/groups/{id}/config     — снять явную настройку (наследовать)
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases import rag
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.permissions.cache import commit_rights

router = APIRouter(tags=["rag"])


def _require(is_super: bool) -> None:
    from app.use_cases.errors import access_denied

    if not is_super:
        raise access_denied("Требуются права системного администратора")


class RagConfigIn(BaseModel):
    chunker: str = Field(min_length=1, max_length=100)
    params: dict = Field(default_factory=dict)
    enabled: bool = True


@router.get("/admin/rag/chunkers")
def list_chunkers_ep(user: CurrentUserDep) -> dict:
    """Реестр чанкеров (встроенные + entry-points) — выпадающий список UI."""
    _require(user.is_super)
    from app.rag import available_chunkers

    return {"chunkers": available_chunkers()}


@router.get("/admin/rag/groups/{group_id}/config")
def get_config_ep(group_id: uuid.UUID, user: CurrentUserDep, db=Depends(get_db)) -> dict:
    _require(user.is_super)
    return rag.get_group_config(db, str(group_id))


@router.put("/admin/rag/groups/{group_id}/config")
def put_config_ep(group_id: uuid.UUID, body: RagConfigIn, user: CurrentUserDep,
                  db=Depends(get_db)) -> dict:
    _require(user.is_super)
    out = rag.upsert_group_config(db, user, str(group_id), body)
    audit_log(db, user, "rag.group_config", "group", group_id,
              details={"chunker": body.chunker, "enabled": body.enabled})
    commit_rights(db)
    return out


@router.delete("/admin/rag/groups/{group_id}/config", status_code=204)
def delete_config_ep(group_id: uuid.UUID, user: CurrentUserDep, db=Depends(get_db)):
    _require(user.is_super)
    rag.delete_group_config(db, str(group_id))
    audit_log(db, user, "rag.group_config_delete", "group", group_id, details={})
    commit_rights(db)
