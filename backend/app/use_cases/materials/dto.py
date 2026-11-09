# DTO материалов.
from app.db import models


def to_out(m: models.Material) -> dict:
    return {
        "id": str(m.id),
        "group_id": str(m.group_id),
        "name": m.name,
        "type_id": str(m.type_id),
        "status": m.status.value if hasattr(m.status, "value") else str(m.status),
        "author_id": str(m.author_id),
        "version": m.version,
        "is_deleted": m.is_deleted,
    }


def to_card(m: models.Material, permissions: dict[str, bool] | None = None) -> dict:
    """Карточка материала (US-037): базовые поля + права пользователя (FR-129)."""
    out = to_out(m)
    out.update({
        "signatory_id": str(m.signatory_id) if m.signatory_id else None,
        "text_content": m.text_content,
        "text_out_of_sync": m.text_out_of_sync,
        "current_file_id": str(m.current_file_id) if m.current_file_id else None,
        "published_at": m.published_at.isoformat() if m.published_at else None,
        "archived_at": m.archived_at.isoformat() if m.archived_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "permissions": permissions or {},
    })
    return out


def to_list_item(m: models.Material) -> dict:
    """Строка списка (FR-112/115–117): сокращённый состав."""
    return {
        "id": str(m.id),
        "name": m.name,
        "group_id": str(m.group_id),
        "type_id": str(m.type_id),
        "status": m.status.value if hasattr(m.status, "value") else str(m.status),
        "author_id": str(m.author_id),
        "version": m.version,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "published_at": m.published_at.isoformat() if m.published_at else None,
    }
