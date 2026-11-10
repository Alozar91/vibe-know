# Доменные ошибки use-cases: RFC 7807 + коды LLD §12.2.
# Сервисы бросают DomainError; api-слой конвертирует в problem+json (app/main.py).
# HTTP-специфика (fastapi.HTTPException) в use-cases не используется.
from dataclasses import dataclass, field


@dataclass(eq=False)
class DomainError(Exception):
    """Бизнес-ошибка сценария: HTTP-статус + доменный код LLD §12.2."""

    status: int
    code: str
    title: str
    detail: str | None = None
    params: dict | None = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.detail or self.title}"


# --- Коды LLD §12.2, используемые этапом 2 ---

def access_denied(detail: str | None = None) -> DomainError:
    """ACCESS_DENIED 403 — нет права/объект невидим (FR-067, FR-104)."""
    return DomainError(
        status=403,
        code="ACCESS_DENIED",
        title="Доступ запрещён",
        detail=detail or "Недостаточно прав для выполнения операции",
    )


def not_found(detail: str | None = None) -> DomainError:
    """RESOURCE_NOT_FOUND 404 — объект не найден или невидим."""
    return DomainError(
        status=404,
        code="RESOURCE_NOT_FOUND",
        title="Объект не найден",
        detail=detail or "Объект не существует или недоступен",
    )


def name_conflict(detail: str | None = None) -> DomainError:
    """NAME_CONFLICT 409 — неуникальное название (FR-017/027; роли — FR-008)."""
    return DomainError(
        status=409,
        code="NAME_CONFLICT",
        title="Конфликт названия",
        detail=detail or "Объект с таким названием уже существует",
    )


def domain_rule_violation(status: int, detail: str) -> DomainError:
    """Нарушение правила, не покрытого отдельным кодом §12.2 (деталь — в detail)."""
    return DomainError(status=status, code="DOMAIN_RULE_VIOLATION", title="Нарушено бизнес-правило", detail=detail)


def self_deactivation_forbidden() -> DomainError:
    """Самодеактивация СА — бизнес-правило этапа 2 (US-004: деактивирует другой СА)."""
    return DomainError(
        status=409,
        code="SELF_DEACTIVATION_FORBIDDEN",
        title="Операция запрещена",
        detail="Нельзя деактивировать собственную учётную запись",
    )


# --- Коды LLD §12.2 этапа 5: жизненный цикл (§4.1) ---

def transition_not_allowed(detail: str | None = None) -> DomainError:
    """TRANSITION_NOT_ALLOWED 409 — нет правила матрицы/защищённый статус (FR-072/073)."""
    return DomainError(
        status=409, code="TRANSITION_NOT_ALLOWED", title="Переход не разрешён",
        detail=detail or "Переход не разрешён матрицей переходов",
    )


def cascade_confirm_required(children_count: int) -> DomainError:
    """CASCADE_CONFIRM_REQUIRED 409 — каскадная архивация без подтверждения (FR-039)."""
    return DomainError(
        status=409, code="CASCADE_CONFIRM_REQUIRED", title="Требуется подтверждение каскада",
        detail="Вместе с мастером будет заархивировано ещё подчинённых материалов: "
        f"{children_count}. Повторите запрос с confirm_cascade=true",
        params={"children_count": children_count},
    )


def master_not_published() -> DomainError:
    """MASTER_NOT_PUBLISHED 409 — публикация подчинённого раньше мастера (FR-042)."""
    return DomainError(
        status=409, code="MASTER_NOT_PUBLISHED", title="Мастер не опубликован",
        detail="Подчинённый материал не может быть опубликован раньше мастера",
    )


def master_status_locked() -> DomainError:
    """MASTER_STATUS_LOCKED 409 — мастер с подчинёнными в «Публикации» (FR-041)."""
    return DomainError(
        status=409, code="MASTER_STATUS_LOCKED", title="Статус мастера заблокирован",
        detail="У мастера есть подчинённые в статусе «Публикация»; "
        "допустим только переход «в Архив» (с каскадом)",
    )


def file_required() -> DomainError:
    """FILE_REQUIRED 409 — переход без файла (FR-028/076)."""
    return DomainError(
        status=409, code="FILE_REQUIRED", title="Файл обязателен",
        detail="Переход невозможен: у материала нет файла; "
        "текстовое представление его не заменяет",
    )


def file_not_ready() -> DomainError:
    """FILE_NOT_READY 409 — переход: файл не прошёл проверку (FR-058, US-015 A1)."""
    return DomainError(
        status=409, code="FILE_NOT_READY", title="Файл не готов",
        detail="Переход невозможен: файл не прошёл антивирусную проверку",
    )


def archived_source_rule_forbidden() -> DomainError:
    """ARCHIVED_SOURCE_RULE_FORBIDDEN 400 — правило матрицы с from_status='archived' (FR-073)."""
    return DomainError(
        status=400, code="ARCHIVED_SOURCE_RULE_FORBIDDEN", title="Правило запрещено",
        detail="Правила с исходным статусом «Архив» запрещены: из архива нет исходящих переходов",
    )
