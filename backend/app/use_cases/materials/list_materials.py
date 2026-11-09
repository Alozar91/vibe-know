# Use-case: список материалов с фильтрами/сортировкой/пагинацией
# (FR-112, FR-115–117, FR-121; US-005 шаг 3).
# Предикат прав §3.2 — inline через visible_materials_condition.
from sqlalchemy import asc, desc, select, func
from sqlalchemy.orm import Session, aliased

from app.db import models
from app.use_cases.common import parse_uuid
from app.use_cases.materials.dto import to_list_item
from app.use_cases.permissions.list_predicate import visible_materials_condition

SORT_FIELDS = {
    "updated_at": models.Material.updated_at,
    "name": models.Material.name,
    "published_at": models.Material.published_at,
    "created_at": models.Material.created_at,
}


def clamp_page(page: int, per_page: int, db: Session | None = None) -> tuple[int, int]:
    """FR-131: per_page 1..200 (по умолчанию — параметр page_size §2.5), page ≥ 1."""
    page = max(1, int(page or 1))
    if per_page:
        per_page = min(200, max(1, int(per_page)))
    else:
        # параметр page_size (FR-121, US-048); 50 — значение сида/фолбэк
        per_page = 50
        if db is not None:
            try:
                from app.use_cases.admin.settings import get_settings_value

                per_page = int(get_settings_value(db, "page_size", 50) or 50)
            except Exception:
                pass  # таблица/параметр отсутствуют — сида достаточно
        per_page = min(200, max(1, per_page))
    return page, per_page


def list_materials(
    db: Session,
    user,
    *,
    group_id: str | None = None,
    include_subgroups: bool = True,
    type_id: str | None = None,
    status: str | None = None,
    author_id: str | None = None,
    include_archive: bool = False,
    permission: str = "view",
    sort: str = "updated_at",
    order: str = "desc",
    page: int = 1,
    per_page: int = 50,
    section: str | None = None,  # my | review | archive (US-006) — или None
) -> dict:
    """Список: фильтры FR-115; сортировка FR-117 (по умолчанию updated_at desc);
    пагинация FR-121."""
    M = models.Material
    G = aliased(models.Group)
    page, per_page = clamp_page(page, per_page, db)

    stmt = select(M).join(G, G.id == M.group_id).where(M.is_deleted.is_(False))

    # --- Служебные разделы (§3.4, US-006) ---
    if section == "my":
        # FR-123: мои — без предиката прав на группы
        stmt = stmt.where(M.author_id == user.user_id)
    elif section == "review":
        # FR-124: на проверке + право review по предикату
        stmt = stmt.where(M.status == models.MaterialStatus.in_review)
        stmt = stmt.where(visible_materials_condition(user, "review", M, G))
    elif section == "archive":
        # FR-125: архив + видимость
        stmt = stmt.where(M.status == models.MaterialStatus.archived)
        stmt = stmt.where(visible_materials_condition(user, "view", M, G))
    else:
        # Обычный список: предикат + фильтр архива (FR-088: скрыт по умолчанию)
        stmt = stmt.where(visible_materials_condition(user, permission, M, G))
        if not include_archive:
            stmt = stmt.where(M.status != models.MaterialStatus.archived)

    # --- Фильтры (FR-115) ---
    if group_id:
        g = db.execute(
            select(models.Group).where(models.Group.id == parse_uuid(group_id))
        ).scalar_one_or_none()
        if g is not None:
            if include_subgroups:
                stmt = stmt.where(G.path.like(f"{g.path}%"))  # вложенные подгруппы
            else:
                stmt = stmt.where(M.group_id == g.id)
    if type_id:
        stmt = stmt.where(M.type_id == parse_uuid(type_id))
    if status:
        try:
            st = models.MaterialStatus(status)
        except ValueError:
            from app.use_cases.errors import DomainError

            raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                              detail="Неизвестный статус")
        stmt = stmt.where(M.status == st)
    if author_id:
        stmt = stmt.where(M.author_id == parse_uuid(author_id))

    # --- Сортировка (FR-117) ---
    col = SORT_FIELDS.get(sort, M.updated_at)
    stmt = stmt.order_by(desc(col) if order == "desc" else asc(col), M.id)

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    rows = db.execute(
        stmt.offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()

    return {
        "items": [to_list_item(m) for m in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }
