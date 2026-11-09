# Use-case: создание группы (FR-015–017, US-052 шаг 1–2) — только СА.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import parse_uuid, require_super
from app.use_cases.errors import DomainError, name_conflict
from app.use_cases.groups.constants import NAME_MAX_LEN
from app.use_cases.groups.dto import to_out


def normalize_name(name: str) -> str:
    """lower(trim(name)); «е»/«ё» не отождествляются (16.1-54) — lower() «ё» не меняет."""
    return name.strip().lower()


def create_group(
    db: Session, is_super: bool, name: str, parent_id: str | None
) -> dict:
    require_super(is_super)
    _validate_name(name)

    parent: models.Group | None = None
    if parent_id is not None:
        parent = db.execute(
            select(models.Group).where(models.Group.id == parse_uuid(parent_id))
        ).scalar_one_or_none()
        if parent is None:
            raise DomainError(status=404, code="RESOURCE_NOT_FOUND", title="Объект не найден",
                              detail="Родительская группа не найдена")
        if parent.is_deleted:
            raise domain_deleted()

    _ensure_name_free(db, name, parent_id=parent.id if parent else None)

    parent_path = parent.path if parent else ""
    g = models.Group(
        name=name.strip(),
        normalized_name=normalize_name(name),
        parent_id=parent.id if parent else None,
        # path строится после flush (нужен id); сегменты — id групп (LLD §2.2)
        path="pending",
    )
    db.add(g)
    db.flush()
    # parent_path завершается "/"; корневой — "". Сегмент = id + "/"
    g.path = f"{parent_path}{g.id}/"
    db.commit()
    return to_out(g)


def _validate_name(name: str) -> None:
    if not name or not name.strip():
        raise DomainError(status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
                          detail="Название группы обязательно")
    if len(name.strip()) > NAME_MAX_LEN:
        raise DomainError(status=400, code="NAME_TOO_LONG", title="Ошибка валидации запроса",
                          detail=f"Название превышает {NAME_MAX_LEN} символов")


def _ensure_name_free(db: Session, name: str, parent_id=None) -> None:
    """Уникальность среди сиблингов (FR-017): без регистра/крайних пробелов; «е»≠«ё»."""
    stmt = select(models.Group).where(
        models.Group.normalized_name == normalize_name(name),
        models.Group.is_deleted.is_(False),
    )
    stmt = stmt.where(models.Group.parent_id == parent_id) if parent_id else stmt.where(
        models.Group.parent_id.is_(None)
    )
    if db.execute(stmt).scalar_one_or_none():
        raise name_conflict("Группа с таким названием уже существует в этом разделе")


def domain_deleted() -> DomainError:
    return DomainError(status=409, code="DOMAIN_RULE_VIOLATION", title="Операция запрещена",
                       detail="Операция над удалённой группой невозможна")
