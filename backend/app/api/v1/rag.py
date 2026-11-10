# RAG — транспорт (RAG_DESIGN §3, §6, §7, §8-1/2/3).
#   СА-контур:
#   GET    /admin/rag/chunkers               — реестр чанкеров (для UI)
#   GET    /admin/rag/groups/{id}/config     — явный + effective конфиг
#   PUT    /admin/rag/groups/{id}/config     — создать/обновить (валидация реестром)
#   DELETE /admin/rag/groups/{id}/config     — снять явную настройку (наследовать)
#   POST   /admin/rag/test-connection        — проверка embedding-провайдера (§6)
#   POST   /admin/rag/materials/{id}:reindex — ручная переиндексация материала
#   POST   /admin/rag/groups/{id}:reindex    — переиндексация поддерева группы
#   Поиск (§7): POST /rag/retrieve — чанки для RAG-консюмеров (права §3.2);
#   GET /search?search_type=vector|hybrid — материалы (FR-133, ранее заглушка).
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases import rag
from app.use_cases.errors import DomainError
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


@router.post("/admin/rag/test-connection")
def test_connection_ep(user: CurrentUserDep) -> dict:
    """Проверка embedding-провайдера до включения индексации (RAG_DESIGN §6)."""
    _require(user.is_super)
    from app.config import get_settings
    from app.rag.embeddings import EmbeddingClient, EmbeddingError

    client = EmbeddingClient(get_settings())
    if not client.enabled:
        raise DomainError(
            status=409, code="RAG_EMBEDDING_NOT_CONFIGURED",
            title="Конфликт данных",
            detail="KB_RAG_EMBEDDING_BASE_URL не задан — конвейер RAG выключен",
        )
    try:
        return client.probe()
    except EmbeddingError as e:
        raise DomainError(
            status=502, code="RAG_EMBEDDING_UNAVAILABLE",
            title="Конфликт данных", detail=str(e),
        ) from e


@router.post("/admin/rag/materials/{material_id}:reindex")
def reindex_material_ep(material_id: uuid.UUID, user: CurrentUserDep,
                        db=Depends(get_db)) -> dict:
    """Ручная переиндексация одного материала (§8-1: ручная переиндексация)."""
    _require(user.is_super)
    from sqlalchemy import select

    from app.db import models

    m = db.execute(select(models.Material).where(models.Material.id == material_id)).scalar_one_or_none()
    if m is None or m.is_deleted:
        raise DomainError(status=404, code="NOT_FOUND", title="Не найдено",
                          detail="Материал не найден")
    from app.rag.indexing import hook_after_change

    hook_after_change(db, m)
    db.commit()
    from app.rag.indexing import flush_rag_enqueue

    flush_rag_enqueue(db)
    audit_log(db, user, "rag.reindex", "material", material_id, details={})
    return {"id": str(material_id), "state": "pending"}


@router.post("/admin/rag/groups/{group_id}:reindex")
def reindex_group_ep(group_id: uuid.UUID, user: CurrentUserDep,
                     db=Depends(get_db)) -> dict:
    """Переиндексация поддерева группы после смены конфига (§3.2, §5)."""
    _require(user.is_super)
    from app.db import models

    g = db.get(models.Group, group_id)
    if g is None or g.is_deleted:
        raise DomainError(status=404, code="NOT_FOUND", title="Не найдено",
                          detail="Группа не найдена")
    try:
        from app.worker.tasks import rag_reindex_group_subtree

        rag_reindex_group_subtree.apply_async(args=[str(group_id)])
    except Exception:
        # Брокер недоступен: штатно (§9) — reconcile поднимет отставших,
        # но для явного запроса СА честно сообщаем.
        raise DomainError(
            status=503, code="QUEUE_UNAVAILABLE", title="Сервис недоступен",
            detail="Брокер задач недоступен; повторите позже",
        ) from None
    audit_log(db, user, "rag.reindex_group", "group", group_id, details={})
    return {"group_id": str(group_id), "state": "enqueued"}


@router.get("/admin/rag/status")
def status_ep(user: CurrentUserDep, db=Depends(get_db),
              limit: int = 50) -> dict:
    """Статус индексации (§8-4): счётчики по rag_state + проблемные материалы.

    pending — хук поставил, задача не дошла (или брокер молчал);
    error — исчерпаны ретраи (embedding-провайдер/чанкер); оба списка —
    рабочие очереди СА. Отставшие поднимет reconcile (beat, §5).
    """
    _require(user.is_super)
    from sqlalchemy import func, select

    from app.db import models

    M = models.Material
    counts = dict(db.execute(
        select(M.rag_state, func.count()).where(M.is_deleted.is_(False))
        .group_by(M.rag_state)
    ).all())

    limit = min(200, max(1, int(limit)))
    problems: list[dict] = []
    rows = db.execute(
        select(M.id, M.name, M.rag_state, M.rag_stale, M.updated_at)
        .where(M.is_deleted.is_(False),
               M.rag_state.in_(["pending", "error"]))
        .order_by(M.updated_at.desc().nullslast())
        .limit(limit)
    ).all()
    for mid, name, st, stale, upd in rows:
        problems.append({
            "id": str(mid), "name": name, "state": st, "stale": stale,
            "updated_at": upd.isoformat() if upd else None,
        })

    total_chunks = db.execute(select(func.count()).select_from(models.RagChunk)).scalar_one()
    return {
        "counts": counts,  # {none: N, pending: N, indexed: N, error: N}
        "problems": problems,
        "total_chunks": total_chunks,
        "limit": limit,
    }


# ==========================================================================
# Поиск по чанкам (RAG_DESIGN §7.1-2): POST /rag/retrieve — права §3.2
# ==========================================================================

class RetrieveIn(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    group_id: str | None = None
    include_subgroups: bool = True
    k: int = Field(default=10, ge=1, le=20)
    mode: str = Field(default="vector", pattern="^(vector|hybrid)$")


@router.post("/rag/retrieve")
def retrieve_ep(body: RetrieveIn, user: CurrentUserDep, db=Depends(get_db)) -> dict:
    """Чанки с оценками для RAG-консюмеров (§7.1-2): права — предикат §3.2.

    Дедуп по материалу (§9-4); k ≤ 20 (§9-5); вызов — в search_events (§7.6).
    """
    from app.use_cases.rag.retrieve import log_retrieve_event, retrieve_chunks

    out = retrieve_chunks(
        db, user,
        q=body.query, group_id=body.group_id,
        include_subgroups=body.include_subgroups,
        k=body.k, mode=body.mode,
    )
    # deep_link для UI/консюмеров (§7.1-2): фронт резолвит маршрут материала
    for it in out["items"]:
        it["deep_link"] = f"/materials/{it['material']['id']}"
    log_retrieve_event(db, body.query, out["total"])
    db.commit()
    return out
