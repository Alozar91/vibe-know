# Search — транспорт (LLD §12.3, §7; FR-110–127, FR-133).
# GET /search, GET /search/groups (блок групп FR-119), POST /search-opens,
# GET /analytics/search (СА, FR-127).
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db import models
from app.db.engine import get_db
from app.use_cases.materials import search_materials as uc

router = APIRouter(tags=["search"])


@router.get("/search")
async def search_ep(
    user: CurrentUserDep,
    db: Session = Depends(get_db),
    q: str | None = None,
    partial: bool = False,
    search_type: str = "fulltext",
    group_id: str | None = None,
    include_subgroups: bool = True,
    type_id: str | None = None,
    status: str | None = None,
    author_id: str | None = None,
    include_archive: bool = False,
    master_filter: str | None = Query(default=None, pattern="^(masters|children)$"),
    sort: str = "relevance",
    order: str = "desc",
    page: int = 1,
    per_page: int | None = None,
    # Атрибутные фильтры — JSON-строка (GET-совместимо; FR-116):
    # [{"attribute_id":"…","op":"eq|substring|range|any_of","value":…,…}]
    attribute_filters: str | None = None,
    tag_ids: str | None = None,  # JSON-строка ["id",…] — any-of (FR-115)
):
    """Глобальный поиск (US-034): выдача материалов + блок групп (FR-119)."""
    import json as _json

    attr_filters = None
    if attribute_filters:
        try:
            attr_filters = _json.loads(attribute_filters)
            if not isinstance(attr_filters, list):
                raise ValueError
        except ValueError:
            from app.use_cases.errors import DomainError

            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail="attribute_filters должен быть JSON-массивом")
    tags = None
    if tag_ids:
        try:
            tags = _json.loads(tag_ids)
            if not isinstance(tags, list):
                raise ValueError
        except ValueError:
            from app.use_cases.errors import DomainError

            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail="tag_ids должен быть JSON-массивом")

    result = uc.search_materials(
        db, user,
        q=q, partial=partial, search_type=search_type,
        group_id=group_id, include_subgroups=include_subgroups,
        type_id=type_id, status=status, author_id=author_id,
        include_archive=include_archive, master_filter=master_filter,
        sort=sort, order=order, page=page, per_page=per_page,
        attribute_filters=attr_filters, tag_ids=tags,
    )
    # Блок групп (FR-119, §7.5): отдельный блок выдачи
    result["groups"] = uc.search_groups(db, user, q or "")
    return result


class SearchOpenIn(BaseModel):
    search_event_id: str
    material_id: str


@router.post("/search-opens")
async def search_opens_ep(
    body: SearchOpenIn,
    user: CurrentUserDep,
    db: Session = Depends(get_db),
):
    """Приём события открытия из выдачи (§7.6, FR-127): fire-and-forget."""
    uc.log_search_open(db, user, body.search_event_id, body.material_id)
    return {"ok": True}


@router.get("/analytics/search")
async def analytics_search_ep(
    user: CurrentUserDep,
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Аналитика поиска (US-051, FR-127): простые списки на MVP.

    Популярные запросы; запросы без результатов; CTR; доля материалов
    с текстом. Персональных данных нет (§7.6). Только СА — аналогично
    другим СА-разделам; require_super в use-case.
    """
    from app.use_cases.common import require_super
    from app.use_cases.errors import DomainError

    if not user.is_super:
        raise DomainError(status=403, code="FORBIDDEN", title="Доступ запрещён",
                          detail="Только системный администратор (FR-104)")

    # Свёртка на лету по raw-событиям (rollup-задача — этап 10/worker);
    # для MVP-списков агрегат по живым данным корректен и проще.
    top = db.execute(
        select(
            models.SearchEvent.query_normalized.label("q"),
            func.count().label("cnt"),
            func.sum(func.coalesce(models.SearchEvent.result_count, 0)).label("hits"),
        )
        .group_by(models.SearchEvent.query_normalized)
        .order_by(desc("cnt")).limit(limit)
    ).all()

    zero = db.execute(
        select(
            models.SearchEvent.query_normalized.label("q"),
            func.count().label("cnt"),
        )
        .where(models.SearchEvent.result_count == 0)
        .group_by(models.SearchEvent.query_normalized)
        .order_by(desc("cnt")).limit(limit)
    ).all()

    total_events = db.execute(select(func.count()).select_from(models.SearchEvent)).scalar_one()
    total_opens = db.execute(select(func.count()).select_from(models.SearchOpen)).scalar_one()
    ctr = round(total_opens / total_events, 4) if total_events else 0.0

    with_text = db.execute(
        select(func.count()).select_from(models.Material).where(
            models.Material.is_deleted.is_(False),
            models.Material.text_content.is_not(None),
        )
    ).scalar_one()
    total_m = db.execute(
        select(func.count()).select_from(models.Material).where(models.Material.is_deleted.is_(False))
    ).scalar_one()
    text_coverage = round(with_text / total_m, 4) if total_m else 0.0

    return {
        "top_queries": [{"query": r.q, "count": r.cnt, "total_results": r.hits} for r in top],
        "zero_result_queries": [{"query": r.q, "count": r.cnt} for r in zero],
        "ctr": {"opens": total_opens, "searches": total_events, "ratio": ctr},
        "text_coverage": {"with_text": with_text, "total": total_m, "ratio": text_coverage},
    }
