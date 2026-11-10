# Общая логика этапа 7 (LLD §4.3, 7.10; FR-032–042, FR-092):
# копирование содержимого (дедуп CAS, без повторного антивируса — FR-057),
# счётчик имён («<имя> <суффикс> (N)» — FR-035/FR-092), инварианты мастера
# (§2.3: один уровень, циклы/самоссылка, материал с подчинёнными — FR-032).
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.errors import DomainError
from app.use_cases.materials.get_material import get_material_or_404
from app.use_cases.materials.versions import commit_version, snapshot_from_material


def _status_v(m: models.Material) -> str:
    return m.status.value if hasattr(m.status, "value") else str(m.status)


def unique_name(db: Session, group_id, base: str) -> str:
    """«<имя> <суффикс>» со счётчиком «(2)», «(3)», … при конфликте (FR-035, FR-092).

    Счётчик применяется к полному имени (CONCEPT 4.3: «<имя> Адаптация (2)»).
    """
    from app.use_cases.materials.create_material import ensure_name_free

    try:
        ensure_name_free(db, group_id, base)
        return base
    except DomainError:
        pass

    n = 2
    while n <= 1000:  # защита от абсурда; конфликт на 1000 копий — не MVP-кейс
        candidate = f"{base} ({n})"
        try:
            ensure_name_free(db, group_id, candidate)
            return candidate
        except DomainError:
            n += 1
    raise DomainError(
        status=409, code="NAME_CONFLICT", title="Конфликт названия",
        detail="Не удалось подобрать уникальное имя (перепробовано 999 счётчиков)",
    )


def copy_content(db: Session, src: models.Material, dst: models.Material) -> None:
    """Копия содержимого мастера/исходника (FR-033, FR-092): файл — тот же
    FileObject (ref_count+1, дедуп NFR-010; повторный антивирус не выполняется —
    FR-057), текст, тип, атрибуты (включая «осиротевшие», FR-051), теги."""
    from app.use_cases.materials.attributes_io import _VALUE_FIELDS

    if src.current_file_id is not None:
        fo = db.execute(
            select(models.FileObject).where(models.FileObject.id == src.current_file_id)
        ).scalar_one()
        dst.current_file_id = fo.id
        db.execute(
            update(models.FileObject)
            .where(models.FileObject.id == fo.id)
            .values(ref_count=models.FileObject.ref_count + 1)
        )

    dst.text_content = src.text_content
    dst.type_id = src.type_id
    dst.text_out_of_sync = src.text_out_of_sync

    # Атрибуты — значениями (копия логически независима, FR-033)
    for av in db.execute(
        select(models.AttributeValue).where(models.AttributeValue.material_id == src.id)
    ).scalars().all():
        fields = {f: getattr(av, f) for f in _VALUE_FIELDS.values()}
        db.add(models.AttributeValue(material_id=dst.id, attribute_id=av.attribute_id, **fields))

    for tid in db.execute(
        select(models.MaterialTag.tag_id).where(models.MaterialTag.material_id == src.id)
    ).scalars().all():
        db.add(models.MaterialTag(material_id=dst.id, tag_id=tid))


def commit_first_version(db: Session, m: models.Material, user) -> None:
    """Версия 1 нового материала — снапшотом текущего состояния (§5.1, FR-144)."""
    commit_version(db, m, user, snapshot=snapshot_from_material(db, m))


def resolve_new_master(
    db: Session, user, master_id: str, child: models.Material
) -> models.Material:
    """Проверки нового мастера (US-026, FR-032/036; US-026 A1 — с пояснением).

    - виден пользователю (FR-108; невидим/не существует → 404, FR-067);
    - статус «Утверждён»/«Публикация»;
    - для подчинённого в «Утверждён»/«Публикация» — только «Публикация» (FR-036);
    - не сам материал и без собственного мастера (FR-032 — один уровень).
    """
    if parse_uuid_or_none(master_id) is None or str(master_id) == str(child.id):
        raise DomainError(
            status=409, code="MASTER_NOT_PUBLISHED", title="Мастер не подходит",
            detail="Ссылка на себя запрещена (FR-032)",
        )
    master = get_material_or_404(db, user, str(master_id))
    ms = _status_v(master)
    if ms not in ("approved", "published"):
        raise DomainError(
            status=409, code="MASTER_NOT_PUBLISHED", title="Мастер не подходит",
            detail="Новый мастер должен быть в статусе «Утверждён» или «Публикация»",
        )
    if master.master_id is not None:
        raise DomainError(
            status=409, code="MASTER_NOT_PUBLISHED", title="Мастер не подходит",
            detail="Подчинённый материал не может быть мастером (FR-032)",
        )
    cs = _status_v(child)
    if cs in ("approved", "published") and ms != "published":
        raise DomainError(
            status=409, code="MASTER_STATUS_LOCKED", title="Недопустимый статус нового мастера",
            detail="Для подчинённого в «Утверждён»/«Публикация» новый мастер — только в «Публикации»",
        )
    return master


def parse_uuid_or_none(v: str):
    from app.use_cases.common import parse_uuid

    return parse_uuid(str(v))


def guard_not_master_with_children(db: Session, m: models.Material) -> None:
    """Материал с неудалёнными подчинёнными — только для move (FR-037/§2.3-2)."""
    has_children = db.execute(
        select(models.Material.id).where(
            models.Material.master_id == m.id, models.Material.is_deleted.is_(False)
        ).limit(1)
    ).first()
    if has_children:
        raise DomainError(
            status=409, code="MASTER_HAS_CHILDREN", title="Материал — мастер",
            detail="Материал с неудалёнными подчинёнными не перемещается",
        )
