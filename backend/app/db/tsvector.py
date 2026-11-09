# Тип tsvector для SQLAlchemy (LLD §7.1): PostgreSQL — TSVECTOR;
# SQLite (pytest) — любое имя типа валидно (динамическая типизация),
# вектор не считается (ветка sqlite в search_common).
from sqlalchemy.types import UserDefinedType


class TSVector(UserDefinedType):
    """materials.search_tsv: не generated — пересчёт сервисом (§7.1)."""

    cached_ok = True

    def get_col_spec(self) -> str:
        return "TSVECTOR"
