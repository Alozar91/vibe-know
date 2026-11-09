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
