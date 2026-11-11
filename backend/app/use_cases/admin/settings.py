# Use-case: реестр параметров системы (LLD §2.5, NFR-020, US-048) — только СА.
#
# GET  /settings  — все параметры с описаниями (значения по умолчанию — сид 0008);
# PUT  /settings/{key} — изменение с валидацией ключа/типа; фиксация в аудите
# (FR-140, action=settings.change, details: {key, old, new}).
# Параметры Keycloak (пароли, сессии) — вне реестра (US-048: консоль Keycloak).
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.use_cases.common import require_super
from app.use_cases.errors import DomainError
from app.use_cases.lifecycle.audit import audit_log

# Ключи, редактируемые через API (§2.5; механические [уточнение LLD] — тоже
# правятся СА, но помечены). smtp_* — составной блок (US-048 ш.1).
EDITABLE_KEYS = {
    "file_max_size_mb": int,
    "mime_extra": list,
    "fts_languages": list,
    "master_change_criterion": str,
    "content_downgrade_params": list,
    "audit_retention_days": (int, type(None)),
    "digest_interval_minutes": (int, type(None)),
    "page_size": int,
    "tags_max": int,
    "attributes_max_per_type": int,
    "name_max_len": int,
    "anti_noise_window_minutes": int,
    "analytics_raw_retention_days": int,
    "keycloak_sync_interval_minutes": int,
    "trgm_similarity_threshold": (int, float),
    "cas_gc_delay_hours": int,
    "short_query_min_len": int,
    "smtp_host": str,
    "smtp_port": int,
    "smtp_from": str,
    "smtp_use_tls": bool,
    # Пост-MVP шаг [7] (RAG_DESIGN §3.1): системный уровень конфигурации RAG.
    # base_url/api_key/model — env (KB_RAG_*), не реестр: секреты и связь
    # с размерностью столбца — вне БД (§3.1, §6).
    "rag.enabled": bool,
    "rag.default_chunker": str,
    "rag.default_params": dict,
}

SMTP_KEYS = {"smtp_host", "smtp_port", "smtp_from", "smtp_use_tls"}


def _validation_error(detail: str) -> DomainError:
    return DomainError(
        status=400, code="VALIDATION_ERROR", title="Ошибка валидации запроса", detail=detail
    )


def list_settings(db: Session, is_super: bool) -> list[dict]:
    """Реестр параметров (US-048 ш.1)."""
    require_super(is_super)
    rows = db.execute(
        select(models.SystemSetting).order_by(models.SystemSetting.key)
    ).scalars().all()
    return [
        {
            "key": r.key,
            "value": r.value,  # JSONB/JSON декодируется SQLAlchemy автоматически
            "description": r.description,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


def get_settings_value(db: Session, key: str, default=None):
    """Чтение одного параметра (для use-cases); None при отсутствии."""
    row = db.execute(
        select(models.SystemSetting).where(models.SystemSetting.key == key)
    ).scalar_one_or_none()
    if row is None:
        return default
    return row.value


def update_setting(db: Session, actor: models.User, is_super: bool, key: str, value) -> dict:
    """Изменение параметра (US-048 ш.3, FR-140) с валидацией."""
    require_super(is_super)
    if key not in EDITABLE_KEYS:
        raise DomainError(
            status=404, code="RESOURCE_NOT_FOUND", title="Параметр не найден",
            detail=f"Ключ «{key}» отсутствует в реестре параметров (§2.5)",
        )

    expected = EDITABLE_KEYS[key]
    if isinstance(expected, tuple):
        if value is not None and not isinstance(value, expected):
            raise _validation_error(f"Значение должно быть {expected} или null")
    elif not isinstance(value, expected):
        raise _validation_error(f"Значение должно быть типа {expected.__name__}")

    # Доменные ограничения (раздел 5 REQUIREMENTS, значения по умолчанию)
    if key in ("file_max_size_mb",) and (not isinstance(value, int) or value < 1):
        raise _validation_error("Размер файла — целое ≥ 1 МБ")
    if key == "master_change_criterion" and value not in ("content", "any"):
        raise _validation_error("Допустимые значения: 'content' | 'any'")
    if key == "page_size" and (not isinstance(value, int) or not (1 <= value <= 200)):
        raise _validation_error("Размер страницы — целое 1..200 (FR-131)")
    if key == "digest_interval_minutes" and value is not None and (
        not isinstance(value, int) or value < 5
    ):
        raise _validation_error("Интервал дайджеста — целое ≥ 5 минут")
    if key == "rag.default_chunker":
        from app.rag import available_chunkers

        if value not in available_chunkers():
            raise _validation_error(
                f"Неизвестный чанкер {value!r}; доступные: {', '.join(available_chunkers())}"
            )
    if key == "rag.enabled" and value not in (True, False):
        raise _validation_error("Значение должно быть true|false")

    row = db.execute(
        select(models.SystemSetting).where(models.SystemSetting.key == key)
    ).scalar_one_or_none()
    if row is None:
        # Ключ из EDITABLE_KEYS, не сидирован (например, smtp_*) — создаём
        row = models.SystemSetting(key=key)
        db.add(row)
    old = row.value
    # JSONB/JSON-колонка: SQLAlchemy сериализует dict/list/скаляры сам
    row.value = value

    audit_log(
        db, actor, "settings.change", "system_setting", None,
        details={"key": key, "old": old, "new": value},
    )
    db.commit()
    return {"key": key, "value": value, "description": row.description}
