# Retrieval (пост-MVP шаг [7] ч.3, RAG_DESIGN §7): векторный и гибридный поиск
# по чанкам с ПРАВАМИ — ровно предикат §3.2 (visible_materials_condition).
#
# Решения §9 (согласованы с заказчиком 10.11.2026):
# - индексируются все статусы (права фильтруют выдачу, §5);
# - гибрид — RRF-слияние FTS-ранка и векторной дистанции (§9-3);
# - /rag/retrieve — дедуп по материалу: один лучший чанк на материал (§9-4);
# - лимиты: k ≤ 20 (§9-5); вызовы — в search_events (аналитика §7.6).
import uuid

from sqlalchemy import and_, case, cast, func, literal, or_, select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.errors import DomainError

MAX_K = 20  # лимит выдачи /rag/retrieve (§9-5)
MAX_Q_LEN = 512
RRF_K = 60  # RRF: score = Σ 1/(60 + rank), rank с 1 в каждом потоке


def _validate_query(q: str | None) -> str:
    q = (q or "").strip()
    if not q:
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Пустой запрос")
    if len(q) > MAX_Q_LEN:
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail=f"Длина запроса ограничена {MAX_Q_LEN} символами")
    return q


def _group_filter(db: Session, group_id: str | None, include_subgroups: bool):
    """Фильтр группы (§7.2) → (path_prefix | None, exact_gid | None).

    include_subgroups=true → path-префикс поддерева; false → строго группа.
    """
    if not group_id:
        return None, None
    try:
        gid = uuid.UUID(group_id)
    except (ValueError, AttributeError, TypeError):
        raise DomainError(status=400, code="VALIDATION_ERROR",
                          title="Ошибка валидации запроса",
                          detail="group_id — не UUID") from None
    g = db.get(models.Group, gid)
    if g is None or g.is_deleted:
        raise DomainError(status=404, code="NOT_FOUND", title="Не найдено",
                          detail="Группа не найдена")
    return (g.path if include_subgroups else None), (None if include_subgroups else gid)


def _query_vector(db: Session, q: str) -> str:
    """Вектор запроса (§6) → строковый литерал для pgvector.

    Конвейер off → 409; сбой провайдера → 502.
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.rag_embedding_base_url:
        raise DomainError(
            status=409, code="RAG_EMBEDDING_NOT_CONFIGURED", title="Конфликт данных",
            detail="Конвейер RAG выключен (KB_RAG_EMBEDDING_BASE_URL не задан)",
        )
    from app.rag.embeddings import EmbeddingClient, EmbeddingError

    try:
        qvec = EmbeddingClient(settings).embed([q])[0]
    except EmbeddingError as e:
        raise DomainError(status=502, code="RAG_EMBEDDING_UNAVAILABLE",
                          title="Конфликт данных", detail=str(e)) from e
    return "[" + ",".join(repr(float(x)) for x in qvec) + "]"


def _chunk_conditions(perm, group_path: str | None, group_exact) -> list:
    C, M, MG = models.RagChunk, models.Material, models.Group
    conds = [M.is_deleted.is_(False), C.embedding.is_not(None), perm]
    if group_path is not None:
        conds.append(MG.path.like(group_path + "%"))
    if group_exact is not None:
        conds.append(M.group_id == group_exact)
    return conds


def _dist_expr(C, vec_literal: str):
    """Дистанция чанк↔вектор-запроса.

    PostgreSQL: pgvector `<=>` (косинусная). SQLite (pytest): заглушка —
    сумма |a-b| по 8 «мерам» хеша текста; детерминизм достаточен для
    сортировки/дедупа, векторная семантика проверяется на живом стеке.
    """
    return C.embedding.op("<=>")(vec_literal)


def _sqlite_dist(C):
    """SQLite-заглушка дистанции: embedding (JSON-список) ↔ хеш content."""
    return func.length(C.content)  # устойчивый порядок; семантика — на PG


def best_chunks_per_material(db: Session, user, *, vec_literal: str,
                             group_path: str | None, group_exact,
                             limit: int) -> list:
    """Лучший чанк на материал (дедуп §9-4): DISTINCT ON (material_id).

    Права — предикат §3.2 inline (§7.3); порядок — ближайшие первыми.
    SQLite (pytest): дистанция-заглушка (длина контента) — механика
    дедупа/сортировки проверяется, семантика — на живом стеке (§7.1).
    """
    C, M, MG = models.RagChunk, models.Material, models.Group
    from app.use_cases.permissions.list_predicate import visible_materials_condition

    perm = visible_materials_condition(user, "view", M, MG)
    is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
    dist = _dist_expr(C, vec_literal) if is_pg else _sqlite_dist(C)
    conds = _chunk_conditions(perm, group_path, group_exact)

    if not is_pg:
        # SQLite (pytest): DISTINCT ON нет — дедуп в Python (объёмы тестовые);
        # дистанция-заглушка — механика дедупа/сортировки, семантика на PG.
        rows = db.execute(
            select(
                C.id.label("chunk_id"),
                C.content.label("content"),
                C.meta.label("meta"),
                C.ord.label("ord"),
                M.id.label("material_id"),
                M.name.label("material_name"),
                M.group_id.label("group_id"),
                M.version.label("material_version"),
                func.length(C.content).label("dist"),  # score=1-d — число
            )
            .select_from(C)
            .join(M, M.id == C.material_id)
            .join(MG, MG.id == M.group_id)
            .where(*conds)
            .limit(limit * 10)
        ).all()
        seen: dict = {}
        for r in rows:  # стабильный порядок выборки
            seen.setdefault(r.material_id, r)
        return list(seen.values())[:limit]

    sub = (
        select(C.id.label("chunk_id"))
        .select_from(C)
        .join(M, M.id == C.material_id)
        .join(MG, MG.id == M.group_id)
        .where(*conds)
        .order_by(C.material_id, dist)
        .distinct(C.material_id)
        .subquery()
    )
    return db.execute(
        select(
            C.id.label("chunk_id"),
            C.content.label("content"),
            C.meta.label("meta"),
            C.ord.label("ord"),
            M.id.label("material_id"),
            M.name.label("material_name"),
            M.group_id.label("group_id"),
            M.version.label("material_version"),
            dist.label("dist"),
        )
        .select_from(C)
        .join(M, M.id == C.material_id)
        .join(MG, MG.id == M.group_id)
        .join(sub, sub.c.chunk_id == C.id)
        .order_by(dist)
        .limit(limit)
    ).all()


def _fts_candidates(db: Session, user, q: str, group_path: str | None,
                    group_exact, limit: int) -> list:
    """FTS-поток гибрида: (material_id, rank) по websearch_to_tsquery + права §3.2.

    Раскладка по distinct search_lang — константный конфиг → GIN (этап 11);
    ранг материала = max ts_rank по конфигам (материал имеет один search_lang).
    SQLite (тесты): ILIKE-ветка без рангов (порядок выборки).
    """
    M, MG = models.Material, models.Group
    from app.use_cases.permissions.list_predicate import visible_materials_condition

    perm = visible_materials_condition(user, "view", M, MG)
    conds = [M.is_deleted.is_(False), perm]
    if group_path is not None:
        conds.append(MG.path.like(group_path + "%"))
    if group_exact is not None:
        conds.append(M.group_id == group_exact)

    is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
    if not is_pg:
        rows = db.execute(
            select(M.id).join(MG, MG.id == M.group_id).where(
                *conds,
                or_(M.name.ilike(f"%{q}%"), M.text_content.ilike(f"%{q}%")),
            ).limit(limit)
        ).scalars().all()
        return [(mid, None) for mid in rows]

    from sqlalchemy.dialects.postgresql import REGCONFIG

    configs = db.execute(select(M.search_lang).distinct()).scalars().all()
    text_conds = []
    for cfg in configs:
        tsq = func.websearch_to_tsquery(cast(literal(cfg), REGCONFIG), q)
        text_conds.append(and_(M.search_lang == cfg, M.search_tsv.op("@@")(tsq)))
    ids = db.execute(
        select(M.id).join(MG, MG.id == M.group_id).where(*conds, or_(*text_conds))
        .limit(limit * 2)
    ).scalars().all()
    if not ids:
        return []
    # Ранги: max ts_rank по конфигам (материал попадает ровно в один конфиг)
    ranks: dict = {}
    for cfg in configs:
        tsq = func.websearch_to_tsquery(cast(literal(cfg), REGCONFIG), q)
        for mid, rk in db.execute(
            select(M.id, func.ts_rank(M.search_tsv, tsq)).where(
                M.id.in_(ids), M.search_lang == cfg, M.search_tsv.op("@@")(tsq))
        ).all():
            if mid not in ranks or rk > ranks[mid]:
                ranks[mid] = rk
    ordered = sorted(ids, key=lambda mid: -ranks.get(mid, 0.0))
    return [(mid, ranks.get(mid)) for mid in ordered]


def retrieve_chunks(db: Session, user, *, q: str, group_id: str | None = None,
                    include_subgroups: bool = True, k: int = 10,
                    mode: str = "vector") -> dict:
    """Поиск по чанкам (RAG_DESIGN §7.1-2): POST /rag/retrieve.

    vector: ближайший чанк каждого видимого материала, ORDER BY дистанция.
    hybrid: RRF-слияние векторного потока и FTS-потока (§7.3, §9-3).
    """
    q = _validate_query(q)
    if k < 1 or k > MAX_K:
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail=f"k должен быть 1..{MAX_K}")
    if mode not in ("vector", "hybrid"):
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="mode — 'vector' | 'hybrid'")
    group_path, group_exact = _group_filter(db, group_id, include_subgroups)

    vec_literal = _query_vector(db, q)
    vec_rows = best_chunks_per_material(
        db, user, vec_literal=vec_literal,
        group_path=group_path, group_exact=group_exact, limit=k * 3,
    )

    if mode == "vector":
        items = [_item(r, round(1.0 - float(r.dist), 6)) for r in vec_rows[:k]]
        return _out(items, q, mode)

    # --- Гибрид (§9-3): RRF двух потоков ---
    fts = _fts_candidates(db, user, q, group_path, group_exact, k * 3)
    items = _rrf_merge(db, user, vec_literal, vec_rows, fts, k)
    return _out(items, q, mode)


def _item(r, score: float | None) -> dict:
    return {
        "content": r.content,
        "meta": r.meta or {},
        "ord": r.ord,
        "score": score,
        "material": {
            "id": str(r.material_id),
            "name": r.material_name,
            "group_id": str(r.group_id),
            "version": r.material_version,
        },
    }


def _rrf_merge(db: Session, user, vec_literal: str, vec_rows, fts, k: int) -> list[dict]:
    """RRF (§9-3): score = Σ 1/(60+rank), rank с 1 в каждом потоке.

    Единица выдачи — материал (дедуп §9-4): векторный поток даёт чанк каждого;
    материалы только из FTS-потока — их ближайший чанк дозапрашивается.
    """
    scores: dict = {}
    for rank, r in enumerate(vec_rows, start=1):
        scores[r.material_id] = {"row": r, "score": 1.0 / (RRF_K + rank)}
    for rank, (mid, _rk) in enumerate(fts, start=1):
        if mid in scores:
            scores[mid]["score"] += 1.0 / (RRF_K + rank)

    # Материалы только из FTS: подтянуть их лучшие чанки одним запросом
    only_fts = [mid for mid, _rk in fts if mid not in scores]
    if only_fts:
        C, M, MG = models.RagChunk, models.Material, models.Group
        from app.use_cases.permissions.list_predicate import visible_materials_condition

        perm = visible_materials_condition(user, "view", M, MG)
        is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
        dist = _dist_expr(C, vec_literal) if is_pg else _sqlite_dist(C)
        rows = db.execute(
            select(C.id.label("chunk_id"), C.content.label("content"),
                   C.meta.label("meta"), C.ord.label("ord"),
                   M.id.label("material_id"), M.name.label("material_name"),
                   M.group_id.label("group_id"), M.version.label("material_version"))
            .select_from(C).join(M, M.id == C.material_id).join(MG, MG.id == M.group_id)
            .where(M.id.in_(only_fts), C.embedding.is_not(None), perm)
            .order_by(M.id, dist).distinct(M.id)
        ).all()
        rows_by_id = {r.material_id: r for r in rows}
        for rank, mid in enumerate(only_fts, start=1):
            row = rows_by_id.get(mid)
            if row is not None:  # без чанков (конвейер off раньше) — материал не выдаём
                scores[mid] = {"row": row, "score": 1.0 / (RRF_K + rank)}

    ordered = sorted(scores.values(), key=lambda e: -e["score"])[:k]
    return [_item(e["row"], round(e["score"], 6)) for e in ordered]


def _out(items: list[dict], q: str, mode: str) -> dict:
    return {"items": items, "total": len(items), "query": q, "mode": mode}


def log_retrieve_event(db: Session, q: str, total: int) -> None:
    """Аналитика (§9-5): вызовы /rag/retrieve — в search_events (§7.6).

    user_id не хранится (без ПДн, §7.6) — как в штатном поиске.
    """
    from app.use_cases.materials.search_materials import normalize_query

    db.add(models.SearchEvent(query_normalized=normalize_query(q), result_count=total))
