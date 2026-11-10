# Use-case: комментарии (LLD §2.2 comments, §12.3; US-038; FR-096–098).
#
# Чтение — всем, кому виден материал (FR-097); создание — участники процесса:
# автор и носители прав edit/review/publish (FR-098); комментарий не
# редактируется и не удаляется (FR-096, таблица без UPDATE/DELETE);
# создание фиксируется в аудите (FR-096); в поиске не участвуют (FR-111).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.errors import DomainError, access_denied
from app.use_cases.lifecycle.audit import audit_log
from app.use_cases.materials.get_material import get_material_or_404

COMMENT_MAX_LEN = 5000  # [уточнение LLD]: ограничение длины не задано §2.2 — сервисное

PROCESS_PERMS = ("edit", "review", "publish")  # участники процесса (FR-098)


def list_comments(db: Session, user, material_id: str) -> dict:
    """Лента комментариев карточки (FR-097): видимость = видимость материала."""
    m = get_material_or_404(db, user, material_id)  # view-видимость (§3.2)
    rows = db.execute(
        select(models.Comment)
        .where(models.Comment.material_id == m.id)
        .order_by(models.Comment.created_at.asc(), models.Comment.id.asc())
    ).scalars().all()
    return {
        "items": [
            {
                "id": str(c.id),
                "material_id": str(c.material_id),
                "author_id": str(c.author_id),
                "text": c.text,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in rows
        ],
        "total": len(rows),
    }


def add_comment(db: Session, user, material_id: str, text: str) -> dict:
    """Новый комментарий (FR-098): участники процесса; аудит comment.create."""
    m = get_material_or_404(db, user, material_id)

    if not user.is_super:  # СА — в обход (FR-104), как в остальных проверках §3.2
        from app.use_cases.permissions.eff import eff_rows, group_chain_ids, has_right

        eff = eff_rows(
            db, user.user_id,
            group_chain_ids(db, m.group.path) if m.group is not None else [],
            material_id=m.id,
        )
        is_author = m.author_id == user.user_id
        if not (is_author or any(has_right(eff, p) for p in PROCESS_PERMS)):
            # A1 US-038: читатель не участник процесса — добавить не может
            raise access_denied("Добавлять комментарии могут только участники процесса")

    clean = (text or "").strip()
    if not clean:
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail="Текст комментария обязателен",
        )
    if len(clean) > COMMENT_MAX_LEN:
        raise DomainError(
            status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса",
            detail=f"Текст комментария превышает {COMMENT_MAX_LEN} символов",
        )

    c = models.Comment(material_id=m.id, author_id=user.user_id, text=clean)
    db.add(c)
    db.flush()

    audit_log(db, user, "comment.create", "material", m.id,
              details={"comment_id": str(c.id)})

    db.commit()
    return {
        "id": str(c.id),
        "material_id": str(c.material_id),
        "author_id": str(c.author_id),
        "text": c.text,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }
