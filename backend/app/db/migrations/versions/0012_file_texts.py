"""Пост-MVP шаг [8]: извлечение текста файлов — таблица file_texts (16.1-121, LLD §2.2)

Revision ID: 0012_file_texts
Revises: 0011_rag_chunks
Create Date: 2026-11-11

Кэш извлечённого текста по файлу (ключ — file_id; sha256 уже в file_objects).
SQLite (pytest) — та же таблица без CHECK-констрейнта state.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0012_file_texts"
down_revision: str | None = "0011_rag_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "file_texts",
        sa.Column("file_id", UUID(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("extractor", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["file_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("file_id", name="pk_file_texts"),
        sa.CheckConstraint(
            "state IN ('pending', 'ready', 'failed')", name="ck_file_texts_state"
        ),
    )
    op.create_index("ix_file_texts_state", "file_texts", ["state"])
    if _is_pg():
        # Частичное совпадение по извлечённому тексту (§7.2, FR-113/114):
        # gin_trgm_ops по text; fastupdate=off — как у остальных GIN поиска (Приложение А №38)
        op.execute(
            "CREATE INDEX ix_file_texts_text_trgm ON file_texts USING gin (text gin_trgm_ops) "
            "WITH (fastupdate = off)"
        )


def downgrade() -> None:
    if _is_pg():
        op.execute("DROP INDEX IF EXISTS ix_file_texts_text_trgm")
    op.drop_index("ix_file_texts_state", table_name="file_texts")
    op.drop_table("file_texts")
