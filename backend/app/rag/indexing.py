# Ядро конвейера индексации (RAG_DESIGN §5): разрешение конфига → чанкование →
# эмбеддинг → замена чанков версии. Отделено от Celery (прямой вызов в тестах).
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import models
from app.rag import registry
from app.rag.embeddings import EmbeddingClient, EmbeddingError
from app.rag.chunkers import content_hash

log = logging.getLogger(__name__)

# Состояния materials.rag_state (RAG_DESIGN §2 — по образцу file_objects):
RAG_STATE_NONE = "none"        # конвейер off / материал вне индексируемого поддерева
RAG_STATE_PENDING = "pending"  # хук поставил, задача ещё не выполнялась
RAG_STATE_INDEXED = "indexed"  # чанки с векторами актуальны
RAG_STATE_ERROR = "error"      # после исчерпания ретраев (чинит reconcile)


def resolve_defaults(db: Session) -> dict:
    """Системный дефолт (§3.1): чанкер/params/enabled, если предки молчат.

    Реестр system_settings: rag.default_chunker / rag.default_params /
    rag.enabled (создаются сидом шага 2; отсутствие — значения по умолчанию).
    """
    rows = db.execute(
        select(models.SystemSetting).where(models.SystemSetting.key.in_(
            ["rag.default_chunker", "rag.default_params", "rag.enabled"]
        ))
    ).scalars().all()
    vals = {r.key: r.value for r in rows}
    return {
        "chunker": vals.get("rag.default_chunker") or "recursive",
        "params": vals.get("rag.default_params") or {},
        "enabled": bool(vals.get("rag.enabled", True)),
    }


def resolve_effective(db: Session, material: models.Material) -> dict | None:
    """Итоговая настройка для материала: ближайший предок ИЛИ системный дефолт.

    enabled=false на любом уровне (группа или система) → None (не индексировать).
    """
    group = db.get(models.Group, material.group_id)
    if group is None or group.is_deleted:
        return None
    defaults = resolve_defaults(db)
    from app.use_cases.rag.group_configs import resolve_config

    eff = resolve_config(db, group.path)
    if eff is not None:
        if not eff.enabled:
            return None
        chunker, params = eff.chunker, dict(eff.params or {})
    else:
        if not defaults["enabled"]:
            return None
        chunker, params = defaults["chunker"], dict(defaults["params"])
    return {"chunker": chunker, "params": params}


def index_material(db: Session, material_id, client: EmbeddingClient | None = None) -> dict:
    """Индексация текущей версии материала (§5, шаги 1–7). Идемпотентна.

    Явно переданный client (тесты) — векторная логика выполняется на любой СУБД.
    Иначе (клиент из настроек): вне PostgreSQL — «skipped» (как fts_rebuild),
    конвейер off (нет base_url) — skipped.
    """
    if client is None:
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            return {"result": "skipped", "reason": "sqlite"}
        client = EmbeddingClient(_settings())
        if not client.enabled:
            return {"result": "skipped", "reason": "embedding off"}

    m = db.get(models.Material, material_id)
    if m is None or m.is_deleted:
        return {"result": "missing"}

    eff = resolve_effective(db, m)
    if eff is None:
        # Вне индексируемого поддерева: убрать устаревшие чанки, state=none
        n = db.execute(delete(models.RagChunk).where(
            models.RagChunk.material_id == m.id)).rowcount or 0
        m.rag_state = RAG_STATE_NONE
        m.rag_stale = False
        db.commit()
        return {"result": "disabled", "chunks_removed": n}

    # Текущая контентная версия — последняя строка material_versions (LLD §5.1:
    # статусы/права/master_id версией не являются, materials.version растёт и от
    # них — number == m.version не гарантирован после перехода статуса; §7.7:
    # «чанки текущей версии» = актуальный контент = последняя версия).
    # Прежний поиск по number == m.version после любого перехода статуса давал
    # missing навсегда (state замирал в pending, reconcile переставлял ежечасно).
    ver = db.execute(
        select(models.MaterialVersion)
        .where(models.MaterialVersion.material_id == m.id)
        .order_by(models.MaterialVersion.number.desc())
        .limit(1)
    ).scalar_one_or_none()
    if ver is None:
        # Контентных версий нет вовсе (аномалия данных): вставлять чанки некуда.
        # Снимаем pending/stale — иначе rag.reconcile переставлял бы задачу вечно
        m.rag_state = RAG_STATE_NONE
        m.rag_stale = False
        db.commit()
        return {"result": "missing"}

    text = _version_text(db, ver)
    if not text or not text.strip():
        # Текста нет (пустышка): чанков не будет — состояние indexed, 0 чанков
        db.execute(delete(models.RagChunk).where(models.RagChunk.material_id == m.id))
        m.rag_state = RAG_STATE_INDEXED
        m.rag_stale = False
        db.commit()
        return {"result": "indexed", "chunks": 0}

    # 0) Fast-path (§5: переиндексировать только при фактическом изменении текста):
    #    чанки этой версии уже этой модели — сравниваем набор content_hash с
    #    результатом чанкования; совпал → эмбеддинг не нужен, только state.
    existing = db.execute(
        select(models.RagChunk.content_hash, models.RagChunk.ord)
        .where(models.RagChunk.version_id == ver.id,
               models.RagChunk.embedding_model == client.model)
        .order_by(models.RagChunk.ord)
    ).all()
    chunker = registry.get_chunker(eff["chunker"])
    if chunker is None:
        raise EmbeddingError(f"чанкер {eff['chunker']!r} исчез из реестра")
    chunks = chunker.chunk(text, eff["params"])
    if existing and [h for h, _o in existing] == [content_hash(c.content) for c in chunks]:
        m.rag_state = RAG_STATE_INDEXED
        m.rag_stale = False
        db.commit()
        return {"result": "unchanged", "chunks": len(chunks)}

    if not chunks:
        db.execute(delete(models.RagChunk).where(models.RagChunk.material_id == m.id))
        m.rag_state = RAG_STATE_INDEXED
        m.rag_stale = False
        db.commit()
        return {"result": "indexed", "chunks": 0}

    # 1) Эмбеддинг пачками (§5-4) — до DELETE/INSERT: сбой провайдера не трогает данные
    texts = [c.content for c in chunks]
    vectors = client.embed(texts)

    # 2) Замена чанков (§5-5/6): чанки прошлых версий не хранятся (§2) —
    #    DELETE по материалу целиком, INSERT чанков текущей версии одной транзакцией
    db.execute(delete(models.RagChunk).where(models.RagChunk.material_id == m.id))
    for i, (c, vec) in enumerate(zip(chunks, vectors)):
        db.add(models.RagChunk(
            material_id=m.id,
            version_id=ver.id,
            group_id=m.group_id,
            ord=i,
            chunker=eff["chunker"],
            content=c.content,
            content_hash=content_hash(c.content),
            meta=dict(c.meta or {}),
            embedding=vec,
            embedding_model=client.model,
        ))
    m.rag_state = RAG_STATE_INDEXED
    m.rag_stale = False
    db.commit()
    log.info("rag.index_material", material=str(m.id), chunks=len(chunks),
             chunker=eff["chunker"])
    return {"result": "indexed", "chunks": len(chunks)}


def _version_text(db: Session, ver: models.MaterialVersion) -> str | None:
    """Текст чанкования (§5-2, 16.1-121): текстовое представление И извлечённый
    текст файла — объединение (приоритет авторского описания — первым).

    Описание: text_content материала; fallback — снапшот версии (FR-144).
    Извлечённый текст: file_texts текущего файла (state='ready', §6.3);
    не готов / не удалось — только описание. Оба пусты → None.
    """
    m = db.get(models.Material, ver.material_id)
    parts: list[str] = []
    if m is not None:
        if m.text_content:
            parts.append(m.text_content)
        else:
            snap = ver.snapshot or {}
            if snap.get("text"):
                parts.append(snap["text"])
        if m.current_file_id is not None:
            ft = db.get(models.FileText, m.current_file_id)
            if ft is not None and ft.state == "ready" and ft.text:
                parts.append(ft.text)
    return "\n\n".join(parts) or None


def _settings():
    from app.config import get_settings

    return get_settings()


def mark_pending(db: Session, material: models.Material) -> None:
    """Хук точки изменения (§5): rag_state='pending', rag_stale=true.

    Коммит — вызывающий (хуки в use-cases материалов); постановка в брокер —
    после коммита (см. enqueue_rag_index).
    """
    material.rag_state = RAG_STATE_PENDING
    material.rag_stale = True


def hook_after_change(db: Session, material: models.Material) -> None:
    """Хук точек изменения текста/версии (§5): тот же вызов, что FTS-хук.

    Ставит pending + регистрирует материал в очереди постановки (в атрибут
    сессии, как _pending_task_refs); постановка в брокер — после коммита.
    Конвейер off (нет base_url) — state не трогаем (остаётся none).
    """
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        return
    if not _settings().rag_embedding_base_url:
        return
    mark_pending(db, material)
    refs = getattr(db, "_pending_rag_refs", None)
    if refs is None:
        refs = []
        db._pending_rag_refs = refs  # noqa: SLF001 — контракт сессии use-case'ов
    refs.append(str(material.id))


def flush_rag_enqueue(db: Session) -> None:
    """Постановка в брокер после коммита (пара к hook_after_change).

    Сбой брокера не мешает ответу: state остаётся pending, подхватит rag.reconcile.
    """
    refs = getattr(db, "_pending_rag_refs", None) or []
    if not refs:
        return
    db._pending_rag_refs = []  # noqa: SLF001
    try:
        from app.worker.tasks import rag_index_material

        for mid in refs:
            try:
                rag_index_material.apply_async(args=[mid])
            except Exception:
                pass
    except Exception:
        pass


def reindex_group_subtree_ids(db: Session, group_path: str) -> list:
    """id материалов поддерева (path LIKE prefix), чьи конфиги могли отнаследовать.

    Поддерево группы целиком: явные настройки подгрупп НЕ переопределяются
    сменой предка, но effective для них мог измениться, если их ближайшая
    настройка — сама изменённая группа (вниз). Точность: reindex_material
    пересчитает resolve_effective для каждого — лишние затраты минимальны.
    """
    from sqlalchemy import func

    rows = db.execute(
        select(models.Material.id).join(models.Group).where(
            models.Group.path.like(f"{group_path}%"),
            models.Material.is_deleted == False,  # noqa: E712
        )
    ).all()
    return [r[0] for r in rows]
