# Use-case: глобальный поиск (LLD §7.3–7.5; FR-110–122, FR-133; US-034–036).
#
# Портируемость: PostgreSQL — полный FTS (websearch_to_tsquery, ts_rank,
# ts_headline) + pg_trgm; SQLite (pytest) — упрощённая ILIKE-ветка: контракт
# API, фильтры и предикат прав проверяются в pytest, FTS/trgm — на живом стеке
# (как файловый конвейер на этапе 6).
import json
from datetime import datetime

from typing import Any

from sqlalchemy import and_, case, func, literal, or_, select, cast, text
from sqlalchemy.orm import Session, aliased

from app.db import models
from app.use_cases.common import parse_uuid
from app.use_cases.errors import DomainError
from app.use_cases.materials.dto import to_list_item
from app.use_cases.permissions.list_predicate import visible_materials_condition

MAX_Q_LEN = 512  # защита от аномальных запросов (не параметр LLD)

HEADLINE_OPTS = "StartSel=<mark>,StopSel=</mark>,MaxFragments=2,MaxWords=35,MinWords=15"


def _is_pg(db: Session) -> bool:
    return db.bind is not None and db.bind.dialect.name == "postgresql"


def normalize_query(q: str | None) -> str:
    """Нормализация для search_events (§7.6): lower, trim."""
    return (q or "").strip().lower()[:MAX_Q_LEN]


def search_materials(
    db: Session,
    user,
    *,
    q: str | None = None,
    partial: bool = False,
    search_type: str = "fulltext",
    group_id: str | None = None,
    include_subgroups: bool = True,
    type_id: str | None = None,
    status: str | None = None,
    author_id: str | None = None,
    include_archive: bool = False,
    master_filter: str | None = None,  # masters | children | None (FR-120)
    sort: str = "relevance",
    order: str = "desc",
    page: int = 1,
    per_page: int = 50,
    attribute_filters: list[dict] | None = None,
    tag_ids: list[str] | None = None,
    log_event: bool = True,
) -> dict:
    """Поиск материалов (US-034/035/036): предикат прав + FTS/trgm + фильтры."""
    if search_type in ("vector", "hybrid"):
        # Пост-MVP шаг [7] ч.3 (RAG_DESIGN §7.1-1, FR-133): векторное/
        # гибридное ранжирование; выдача — материалы (как в fulltext).
        return _vector_search(
            db, user,
            q=q, search_type=search_type,
            group_id=group_id, include_subgroups=include_subgroups,
            type_id=type_id, status=status, author_id=author_id,
            include_archive=include_archive, master_filter=master_filter,
            page=page, per_page=per_page,
            attribute_filters=attribute_filters, tag_ids=tag_ids,
            log_event=log_event,
        )
    if search_type != "fulltext":
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="search_type — 'fulltext' | 'vector' | 'hybrid'")
    q = (q or "").strip()
    if len(q) > MAX_Q_LEN:
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail=f"Длина запроса ограничена {MAX_Q_LEN} символами")
    page = max(1, int(page or 1))
    if per_page:
        per_page = min(200, max(1, int(per_page)))
    else:
        # параметр page_size (FR-121, US-048)
        per_page = 50
        try:
            from app.use_cases.admin.settings import get_settings_value

            per_page = int(get_settings_value(db, "page_size", 50) or 50)
        except Exception:
            pass
        per_page = min(200, max(1, per_page))
    is_pg = _is_pg(db)

    M = models.Material
    G = aliased(models.Group)
    stmt = select(M).join(G, G.id == M.group_id).where(M.is_deleted.is_(False))

    # --- Видимость (FR-112): предикат §3.2 inline; архив скрыт (FR-088) ---
    stmt = stmt.where(visible_materials_condition(user, "view", M, G))
    if not include_archive:
        stmt = stmt.where(M.status != models.MaterialStatus.archived)

    # --- Фильтры (FR-115/116/120, §7.3) ---
    stmt = _apply_filters(
        db, stmt, M, G,
        group_id=group_id, include_subgroups=include_subgroups,
        type_id=type_id, status=status, author_id=author_id,
        master_filter=master_filter, attribute_filters=attribute_filters,
        tag_ids=tag_ids,
    )

    # --- Текстовые условия (§7.3) ---
    from sqlalchemy.dialects.postgresql import REGCONFIG

    text_conds = []
    tsq_by_cfg: dict[str, Any] = {}
    if q:
        if is_pg:
            # websearch_to_tsquery(search_lang::regconfig, q) — конфигурация
            # материала (FR-122/9.7); не бросает синтаксических ошибок (§7.3).
            # Этап 11 (NFR-001): tsquery в форме «от колонки» (cast(m.search_lang…))
            # не извлекается в условие GIN-индекса → merge join по всей таблице
            # (p95 поиска 10 с). Раскладываем по distinct search_lang: константный
            # конфиг → GIN BitmapOr; семантика «конфигурация материала» та же.
            configs = db.execute(select(M.search_lang).distinct()).scalars().all()
            for cfg in configs:
                tsq_by_cfg[cfg] = func.websearch_to_tsquery(cast(literal(cfg), REGCONFIG), q)
                text_conds.append(
                    and_(M.search_lang == cfg, M.search_tsv.op("@@")(tsq_by_cfg[cfg]))
                )
            if partial:
                threshold = _setting(db, "trgm_similarity_threshold", 0.3)
                short_len = _setting(db, "short_query_min_len", 3)
                # FR-114: «парацет» находит «Парацетамол» — ILIKE по подстроке
                # (ускоряется тем же GIN trgm-индексом, §7.2 [уточнение LLD] —
                # Приложение А №30) и name % q (pg_trgm similarity, оператор —
                # индексируем; Приложение А №36: similarity(text_content, q) для
                # длинных текстов математически недостижима (порог 0.3), а её
                # неиндексируемая форма давала seq scan → p95 11 с).
                # Порог оператора % — тот же параметр реестра (§2.5).
                if len(q) >= short_len:
                    db.execute(text(f"SET LOCAL pg_trgm.similarity_threshold = {float(threshold)}"))
                # короткие: только ILIKE (trgm-similarity на «абв» бессмысленна)
                conds = [M.name.ilike(f"%{q}%"), M.text_content.ilike(f"%{q}%")]
                if len(q) >= short_len:
                    conds.append(M.name.op("%")(q))
                text_conds.append(or_(*conds))
        else:
            # SQLite: ILIKE-ветка (контракт/права; FTS-семантика — на живом стеке)
            text_conds.append(M.name.ilike(f"%{q}%"))
            if partial:
                text_conds.append(M.text_content.ilike(f"%{q}%"))
    if text_conds:
        stmt = stmt.where(or_(*text_conds))

    # --- Сортировка (FR-117, §7.4) ---
    if q and sort == "relevance" and is_pg:
        # 0.7 * ts_rank + 0.3 * similarity ([уточнение LLD], §14-1);
        # ts_rank — с константным tsquery раскладки по конфигам (выше).
        def _rank(cfg: str) -> Any:
            return func.ts_rank(M.search_tsv, tsq_by_cfg[cfg])

        relevance = case(
            *[(and_(M.search_lang == cfg), _rank(cfg)) for cfg in tsq_by_cfg],
            else_=0.0,
        )
        relevance = 0.7 * relevance + 0.3 * func.similarity(M.name, q)
        stmt = stmt.order_by(relevance.desc() if order == "desc" else relevance.asc(), M.id)
    else:
        col = _sort_field(sort if sort != "relevance" else "updated_at")
        stmt = stmt.order_by(col.desc() if order == "desc" else col.asc(), M.id)

    # --- Пагинация (FR-121) + total (COUNT по предикату, §7.4) ---
    # Этап 11 (NFR-001): COUNT — по подзапросу БЕЗ ORDER BY: иначе PG вычисляет
    # ts_rank/similarity и сортирует все совпавшие строки ради подсчёта.
    count_stmt = stmt.order_by(None) if q and sort == "relevance" else stmt
    total = db.execute(select(func.count()).select_from(count_stmt.subquery())).scalar_one()
    rows = db.execute(stmt.offset((page - 1) * per_page).limit(per_page)).scalars().all()

    # Подсветка (FR-118): один батч-запрос по id страницы (этап 11: прежний N+1
    # — 20 отдельных round-trips на поиск — давал латентность под нагрузкой);
    # название подсвечивает клиент (§7.4)
    headlines: dict[str, str] = {}
    if q and is_pg and rows:
        from sqlalchemy.dialects.postgresql import REGCONFIG

        hl_conf = cast(models.Material.search_lang, REGCONFIG)
        hl_rows = db.execute(
            select(
                models.Material.id,
                func.ts_headline(
                    hl_conf,
                    func.coalesce(models.Material.text_content, ""),
                    func.websearch_to_tsquery(hl_conf, q),
                    HEADLINE_OPTS,
                ),
            ).where(models.Material.id.in_([m.id for m in rows]))
        ).all()
        headlines = {str(mid): hl for mid, hl in hl_rows}

    items = []
    for m in rows:
        item = to_list_item(m)
        if q and is_pg:
            item["headline"] = headlines.get(str(m.id), "")
        items.append(item)

    # --- Аналитика (§7.6, FR-127): факт запроса; id — для search_opens ---
    event_id = None
    if q and log_event:
        ev = models.SearchEvent(query_normalized=normalize_query(q), result_count=total)
        db.add(ev)
        db.flush()
        event_id = str(ev.id)
        db.commit()

    return {
        "items": items,
        "groups": [],
        "total": total,
        "page": page,
        "per_page": per_page,
        "query": q,
        "search_event_id": event_id,
    }


def search_groups(db: Session, user, q: str) -> list[dict]:
    """Блок групп в выдаче (FR-119, §7.5): trgm/ILIKE + право view по предикату."""
    q = (q or "").strip()
    if not q or len(q) > MAX_Q_LEN:
        return []
    Gr = models.Group
    stmt = select(Gr).where(Gr.is_deleted.is_(False))
    if _is_pg(db):
        threshold = _setting(db, "trgm_similarity_threshold", 0.3)
        short_len = _setting(db, "short_query_min_len", 3)
        if len(q) < short_len:
            stmt = stmt.where(Gr.name.ilike(f"%{q}%"))
        else:
            stmt = stmt.where(or_(
                func.similarity(Gr.name, q) > threshold,
                Gr.name.ilike(f"%{q}%"),
            ))
    else:
        stmt = stmt.where(Gr.name.ilike(f"%{q}%"))
    rows = db.execute(stmt.order_by(Gr.name)).scalars().all()

    from app.use_cases.permissions.can import can_group

    out = []
    for g in rows:
        if can_group(db, user, str(g.id), "view"):
            out.append({"id": str(g.id), "name": g.name, "path": g.path})
    return out


def log_search_open(db: Session, user, search_event_id: str, material_id: str) -> None:
    """POST /search-opens (§7.6): fire-and-forget; ошибки приёма не влияют на переход."""
    ev = db.execute(
        select(models.SearchEvent).where(models.SearchEvent.id == parse_uuid(search_event_id))
    ).scalar_one_or_none()
    m = db.execute(
        select(models.Material.id).where(
            models.Material.id == parse_uuid(material_id), models.Material.is_deleted.is_(False)
        )
    ).scalar_one_or_none()
    if ev is None or m is None:
        # Событие не найдено/материал недоступен — молча игнорируем (fire-and-forget)
        return
    db.add(models.SearchOpen(search_event_id=ev.id, material_id=m))
    db.commit()


def _apply_filters(db: Session, stmt, M, G, *, group_id, include_subgroups,
                   type_id, status, author_id, master_filter, attribute_filters, tag_ids):
    """Фильтры FR-115/116/120 (§7.3) — те же, что в списках (FR-115)."""
    if group_id:
        g = db.execute(
            select(models.Group).where(models.Group.id == parse_uuid(group_id))
        ).scalar_one_or_none()
        if g is not None:
            if include_subgroups:
                stmt = stmt.where(G.path.like(f"{g.path}%"))
            else:
                stmt = stmt.where(M.group_id == g.id)
    if type_id:
        stmt = stmt.where(M.type_id == parse_uuid(type_id))
    if status:
        try:
            st = models.MaterialStatus(status)
        except ValueError:
            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail="Неизвестный статус")
        stmt = stmt.where(M.status == st)
    if author_id:
        stmt = stmt.where(M.author_id == parse_uuid(author_id))
    if master_filter == "masters":
        stmt = stmt.where(M.master_id.is_(None))
    elif master_filter == "children":
        stmt = stmt.where(M.master_id.is_not(None))
    if tag_ids:
        ids = [parse_uuid(t) for t in tag_ids if t]
        if ids:
            stmt = stmt.where(M.id.in_(
                select(models.MaterialTag.material_id).where(models.MaterialTag.tag_id.in_(ids))
            ))
    for f in attribute_filters or []:
        stmt = _apply_attribute_filter(db, stmt, M, f)
    return stmt


def _apply_attribute_filter(db: Session, stmt, M, f: dict):
    """Один атрибутный фильтр (FR-116): операторы по типу значения.

    f: {attribute_id, op: eq|substring|range|any_of,
        value / value_from+value_to / values}
    Многозначные — any-of естественно (строк в attribute_values несколько).
    """
    attr = db.execute(
        select(models.Attribute).where(
            models.Attribute.id == parse_uuid(str(f.get("attribute_id") or ""))
        )
    ).scalar_one_or_none()
    if attr is None:
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Неизвестный атрибут в фильтре")
    op_name = (f.get("op") or "eq").strip()
    AV = models.AttributeValue

    def _by_av(*conds):
        return M.id.in_(select(AV.material_id).where(AV.attribute_id == attr.id, *conds))

    if op_name == "eq":
        v = f.get("value")
        if v in (None, ""):
            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail="Не задано значение фильтра")
        stmt = stmt.where(_by_av(_eq_condition(attr, v)))
    elif op_name == "substring":
        v = str(f.get("value") or "")
        if not v:
            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail="Не задано значение фильтра")
        if _value_type(attr) == "dictionary":
            # справочник — фильтруется значением (FR-116): точное совпадение по тексту
            stmt = stmt.where(_by_av(AV.dictionary_value_id.in_(
                select(models.DictionaryValue.id).where(models.DictionaryValue.value == v)
            )))
        else:
            stmt = stmt.where(_by_av(_value_column(attr).ilike(f"%{v}%")))
    elif op_name == "range":
        lo, hi = f.get("value_from"), f.get("value_to")
        if lo in (None, "") and hi in (None, ""):
            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail="Не заданы границы диапазона")
        conds = []
        if lo not in (None, ""):
            conds.append(_value_column(attr) >= _coerce(attr, lo))
        if hi not in (None, ""):
            conds.append(_value_column(attr) <= _coerce(attr, hi))
        stmt = stmt.where(_by_av(*conds))
    elif op_name == "any_of":
        values = [v for v in (f.get("values") or []) if v not in (None, "")]
        if not values:
            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail="Не заданы значения фильтра")
        stmt = stmt.where(_by_av(or_(*[_eq_condition(attr, v) for v in values])))
    else:
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail=f"Неизвестный оператор фильтра: {op_name}")
    return stmt


def _value_type(attr: models.Attribute) -> str:
    return attr.value_type.value if hasattr(attr.value_type, "value") else str(attr.value_type)


def _value_column(attr: models.Attribute):
    """Колонка значения по value_type (LLD §2.2)."""
    return {
        "string": models.AttributeValue.value_string,
        "number": models.AttributeValue.value_number,
        "date": models.AttributeValue.value_date,
        "url": models.AttributeValue.value_url,
        "dictionary": models.AttributeValue.dictionary_value_id,
    }.get(_value_type(attr), models.AttributeValue.value_string)


def _eq_condition(attr: models.Attribute, value):
    """Точное совпадение по типу (FR-116); справочник — по id значения."""
    vt = _value_type(attr)
    if vt == "number":
        return models.AttributeValue.value_number == float(value)
    if vt == "date":
        return models.AttributeValue.value_date == datetime.fromisoformat(str(value))
    if vt == "dictionary":
        return models.AttributeValue.dictionary_value_id == parse_uuid(str(value))
    return models.AttributeValue.value_string == str(value)


def _coerce(attr: models.Attribute, value):
    """Приведение границы диапазона к типу колонки (FR-116)."""
    vt = _value_type(attr)
    if vt == "number":
        return float(value)
    if vt == "date":
        return datetime.fromisoformat(str(value))
    return value


def _sort_field(sort: str):
    """Допустимые поля сортировки (FR-117)."""
    return {
        "name": models.Material.name,
        "updated_at": models.Material.updated_at,
        "published_at": models.Material.published_at,
        "created_at": models.Material.created_at,
    }.get(sort, models.Material.updated_at)


def _setting(db: Session, key: str, default):
    """Чтение параметра реестра §2.5 (system_settings; NFR-020).
    Значение JSONB декодировано SQLAlchemy — json.loads не нужен."""
    from app.use_cases.admin.settings import get_settings_value

    return get_settings_value(db, key, default)


# ==========================================================================
# Пост-MVP шаг [7] ч.3 (RAG_DESIGN §7.1-1, FR-133): search_type=vector|hybrid —
# векторное/гибридное ранжирование, выдача — материалы (как в fulltext).
# ==========================================================================

def _vector_search(
    db: Session,
    user,
    *,
    q: str | None,
    search_type: str,
    group_id: str | None,
    include_subgroups: bool,
    type_id: str | None,
    status: str | None,
    author_id: str | None,
    include_archive: bool,
    master_filter: str | None,
    page: int,
    per_page: int | None,
    attribute_filters: list[dict] | None,
    tag_ids: list[str] | None,
    log_event: bool,
) -> dict:
    """Поиск материалов, ранжированный по чанкам (вектор) или RRF (гибрид).

    Материальные фильтры и права — как в fulltext (один предикат §3.2);
    порядок материалов — по лучшему чанку (дедуп §9-4) / RRF-слиянию.
    Конвейер RAG off → 409 (честная ошибка вместо тихого фолбэка — §7.1-1).
    """
    from app.use_cases.rag import retrieve as rag_ret

    q = rag_ret._validate_query(q)
    page = max(1, int(page or 1))
    if per_page:
        per_page = min(200, max(1, int(per_page)))
    else:
        per_page = 50
        try:
            from app.use_cases.admin.settings import get_settings_value

            per_page = int(get_settings_value(db, "page_size", 50) or 50)
        except Exception:
            pass
        per_page = min(200, max(1, per_page))

    # Фильтр группы §7.2 — та же валидация, что у /rag/retrieve
    group_path, group_exact = rag_ret._group_filter(db, group_id, include_subgroups)

    # Вектор запроса (409/502 при off/сбое — §7.1-1)
    vec_literal = rag_ret._query_vector(db, q)

    M, MG = models.Material, models.Group
    from app.use_cases.permissions.list_predicate import visible_materials_condition

    perm = visible_materials_condition(user, "view", M, MG)

    # Базовые материальные условия: права + фильтры (FR-112/115/116/120)
    m_conds = [M.is_deleted.is_(False)]
    if not include_archive:
        m_conds.append(M.status != models.MaterialStatus.archived)
    if group_path is not None:
        m_conds.append(MG.path.like(group_path + "%"))
    if group_exact is not None:
        m_conds.append(M.group_id == group_exact)
    if type_id:
        m_conds.append(M.type_id == __import__("uuid").UUID(type_id))
    if status:
        m_conds.append(M.status == status)
    if author_id:
        m_conds.append(M.author_id == __import__("uuid").UUID(author_id))
    if master_filter == "masters":
        m_conds.append(M.master_id.is_(None))
    elif master_filter == "children":
        m_conds.append(M.master_id.is_not(None))

    # Атрибутные/теговые фильтры — та же логика, что в fulltext (§7.3)
    extra: list = []
    if attribute_filters:
        for f in attribute_filters:
            extra.append(_apply_attribute_filter(db, select(M), M, f))
    if tag_ids:
        T = models.MaterialTag
        extra.append(select(M.id).join(T, T.material_id == M.id).where(T.tag_id.in_(tag_ids)))

    # --- Поток ранжирования: векторный (лучший чанк материала) ---
    vec_rows = rag_ret.best_chunks_per_material(
        db, user, vec_literal=vec_literal,
        group_path=group_path, group_exact=group_exact,
        # без limit: дедуп всех видимых материалов для сортировки+пагинации
        limit=100000,
    )
    order_by_material = {r.material_id: i for i, r in enumerate(vec_rows)}

    if search_type == "hybrid":
        fts = rag_ret._fts_candidates(db, user, q, group_path, group_exact, 200)
        fts_order = {mid: i for i, (mid, _rk) in enumerate(fts)}
    else:
        fts_order = {}

    # Ранг материала: min порядок в потоках → RRF-скор (§9-3) или чистый вектор
    def _rank(mid) -> float:
        vr = order_by_material.get(mid)
        fr = fts_order.get(mid)
        if search_type == "hybrid":
            s = 0.0
            if vr is not None:
                s += 1.0 / (rag_ret.RRF_K + vr + 1)
            if fr is not None:
                s += 1.0 / (rag_ret.RRF_K + fr + 1)
            return s
        # vector: дистанция лучшего чанка (меньше — лучше) → score 1-d
        row = vec_rows[vr] if vr is not None else None
        return 1.0 - float(row.dist) if row is not None else -1.0

    # Кандидаты: материалы, подходящие под фильтры и права; сортировка — ранг
    stmt = select(M).join(MG, MG.id == M.group_id).where(*m_conds, perm)
    for e in extra:
        stmt = stmt.where(M.id.in_(e.scalar_subquery()))
    # master_filter 'masters'|'children' уже в m_conds

    candidates = db.execute(stmt.order_by(M.updated_at.desc().nullslast(), M.id)).scalars().all()
    candidates.sort(key=_rank, reverse=True)

    total = len(candidates)
    rows = candidates[(page - 1) * per_page: page * per_page]

    items = [to_list_item(m) for m in rows]

    # Аналитика (§7.6, FR-127)
    event_id = None
    if log_event:
        from app.use_cases.materials.search_materials import normalize_query

        ev = models.SearchEvent(query_normalized=normalize_query(q), result_count=total)
        db.add(ev)
        db.flush()
        event_id = str(ev.id)
        db.commit()

    return {
        "items": items,
        "groups": [],
        "total": total,
        "page": page,
        "per_page": per_page,
        "query": q,
        "search_event_id": event_id,
    }
