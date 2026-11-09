# Базовый класс моделей (LLD §2.2: ключи uuid — UUIDv7 в приложении; даты — timestamptz UTC).
import uuid

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Соглашение об именах ограничений — единообразные миграции (Alembic)
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=naming_convention)


def new_uuid() -> uuid.UUID:
    """UUIDv7 — монотонность для индексов (LLD §2.2)."""
    return uuid.uuid7()


class TimestampMixin:
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
