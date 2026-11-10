# Use-cases RAG-конфигурации групп (RAG_DESIGN §3): CRUD СА + разрешение
# по цепочке предков (ближайшая группа с явной настройкой; materialized path).
import uuid

from sqlalchemy import select, text

from app.db import models
from app.rag import available_chunkers
from app.use_cases.errors import DomainError, not_found


def resolve_config(db: Session, group_path: str) -> models.RagGroupConfig | None:
    """Ближайшая явная настройка по цепочке предков группы (§3.2).

    group_path — materialized path '/id1/…/idN/'. Подгруппа наследует
    ближайшего предка с собственной строкой; не нашли — None (системный
    дефолт решает вызывающий: настройка rag.default_chunker — шаг 2 плана).
    """
    parents = [p for p in group_path.split("/") if p]
    if not parents:
        return None
    if db.bind is not None and db.bind.dialect.name != "postgresql":
        # SQLite (pytest): предки по path простым перебором
        for gid in reversed(parents):
            cfg = db.execute(
                select(models.RagGroupConfig).where(
                    models.RagGroupConfig.group_id == uuid.UUID(gid)
                )
            ).scalar_one_or_none()
            if cfg is not None:
                return cfg
        return None
    # PostgreSQL: предки в порядке пути (дальний → ближний), берём последнюю
    rows = db.execute(
        text(
            """
            SELECT gc.id FROM rag_group_configs gc
            JOIN groups g ON g.id = gc.group_id
            JOIN unnest(CAST(:ids AS uuid[])) WITH ORDINALITY AS t(id, ord)
              ON g.id = t.id
            WHERE g.is_deleted = false
            ORDER BY t.ord DESC
            LIMIT 1
            """
        ),
        {"ids": parents},
    ).mappings().first()
    if not rows:
        return None
    return db.get(models.RagGroupConfig, rows["id"])


def _own(db: Session, group_id: uuid.UUID) -> models.RagGroupConfig | None:
    return db.execute(
        select(models.RagGroupConfig).where(models.RagGroupConfig.group_id == group_id)
    ).scalar_one_or_none()


def _validate(db: Session, chunker: str, params: dict, group_id: uuid.UUID) -> None:
    if chunker not in available_chunkers():
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail=f"Неизвестный чанкер {chunker!r}; доступные: {', '.join(available_chunkers())}",
        )
    if not isinstance(params, dict):
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail="params должен быть объектом",
        )
    g = db.get(models.Group, group_id)
    if g is None or g.is_deleted:
        raise not_found("Группа не найдена")


def _dump(c: models.RagGroupConfig) -> dict:
    return {
        "group_id": str(c.group_id),
        "chunker": c.chunker,
        "params": c.params,
        "enabled": c.enabled,
        "updated_at": c.created_at.isoformat() if c.created_at else None,
        "updated_by": str(c.updated_by),
    }


def get_group_config(db: Session, group_id: str) -> dict:
    """Конфиг группы (явный) + effective (разрешённый по цепочке) — для UI."""
    gid = uuid.UUID(group_id)
    g = db.get(models.Group, gid)
    if g is None or g.is_deleted:
        raise not_found("Группа не найдена")
    own = _own(db, gid)
    eff = resolve_config(db, g.path)
    return {
        "group_id": str(gid),
        "chunkers": available_chunkers(),
        "own": None if own is None else _dump(own),
        "effective": None if eff is None else _dump(eff),
        "inherit_from": (
            str(eff.group_id) if eff is not None and (own is None or eff.group_id != own.group_id)
            else None
        ),
    }


def upsert_group_config(db: Session, actor, group_id: str, body) -> dict:
    """Создание/обновление явной настройки группы (СА; аудит — вызывающим)."""
    gid = uuid.UUID(group_id)
    _validate(db, body.chunker, body.params, gid)
    own = _own(db, gid)
    if own is None:
        own = models.RagGroupConfig(group_id=gid, updated_by=actor.user_id)
        db.add(own)
    own.chunker = body.chunker
    own.params = body.params
    own.enabled = body.enabled
    own.updated_by = actor.user_id
    db.commit()
    return _dump(own)


def delete_group_config(db: Session, group_id: str) -> None:
    """Снять явную настройку → подгруппы снова наследуют предков."""
    gid = uuid.UUID(group_id)
    own = _own(db, gid)
    if own is None:
        raise not_found("Настройка группы не найдена")
    db.delete(own)
    db.commit()
