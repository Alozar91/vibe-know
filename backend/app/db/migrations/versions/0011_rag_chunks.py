"""Пост-MVP шаг [7], часть 1: RAG — чанки, конфиг групп (RAG_DESIGN §2, §8-1)

Revision ID: 0011_rag_chunks
Revises: 0010_search_gin_tuning
Create Date: 2026-11-10

pgvector — только PostgreSQL: CREATE EXTENSION, столбец vector(RAG_EMBEDDING_DIM)
и HNSW-индекс в ветке postgresql; SQLite (pytest) — те же таблицы с TEXT-столбцом
embedding (динамическая типизация), векторные ветки поиска не выполняются.
Размерность фиксирует env KB_RAG_EMBEDDING_DIM (по умолчанию 1536) на момент
миграции; смена модели/размерности = новая миграция + полный переиндекс
(RAG_DESIGN §2, §9-1).
"""
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.vector import Vector

revision: str = "0011_rag_chunks"
down_revision: str | None = "0010_search_gin_tuning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIM = int(os.getenv("KB_RAG_EMBEDDING_DIM", "1536") or 1536)


def _is_pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_pg():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "rag_group_configs",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("group_id", UUID(), nullable=False),
        sa.Column("chunker", sa.Text(), nullable=False),
        sa.Column("params", JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_by", UUID(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_rag_group_configs"),
    )
    op.create_index("uq_rag_group_configs_group", "rag_group_configs", ["group_id"], unique=True)
    # Дефолт {} для params (server_default jsonb — лишний литерал в DDL; проще заполнить)
    op.execute('UPDATE rag_group_configs SET params = \'{}\' WHERE params IS NULL')

    op.create_table(
        "rag_chunks",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("material_id", UUID(), nullable=False),
        sa.Column("version_id", UUID(), nullable=False),
        sa.Column("group_id", UUID(), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("chunker", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("meta", JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("embedding", Vector(DIM) if _is_pg() else sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["material_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.PrimaryKeyConstraint("id", name="pk_rag_chunks"),
    )
    op.create_index("uq_rag_chunks_version_ord", "rag_chunks", ["version_id", "ord"], unique=True)
    op.create_index("ix_rag_chunks_material", "rag_chunks", ["material_id"])
    op.create_index("ix_rag_chunks_group", "rag_chunks", ["group_id"])

    # --- Состояние конвейера на материале (§2, по образцу file_objects §6.4) ---
    op.add_column(
        "materials",
        sa.Column("rag_state", sa.String(16), nullable=False, server_default="none"),
    )
    op.add_column(
        "materials",
        sa.Column("rag_stale", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_materials_rag_stale", "materials", ["rag_stale"])

    # --- Сид параметров RAG (§3.1: системный уровень — реестр настроек) ---
    rag_seed = [
        ("rag.enabled", "true", "RAG (пост-MVP шаг [7]): конвейер индексации включён"),
        ("rag.default_chunker", '"recursive"', "RAG: чанкер по умолчанию (без явной настройки группы)"),
        ("rag.default_params", "{}", "RAG: параметры чанкера по умолчанию"),
    ]
    for key, value, description in rag_seed:
        op.execute(
            sa.text(
                "INSERT INTO system_settings (key, value, description) "
                "VALUES (:k, CAST(:v AS jsonb), :d)"
            ).bindparams(k=key, v=value, d=description)
        )

    if _is_pg():
        op.execute(
            "CREATE INDEX ix_rag_chunks_hnsw ON rag_chunks "
            "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    if _is_pg():
        op.execute("DROP INDEX IF EXISTS ix_rag_chunks_hnsw")
    op.execute("DELETE FROM system_settings WHERE key LIKE 'rag.%'")
    op.drop_index("ix_materials_rag_stale", table_name="materials")
    op.drop_column("materials", "rag_stale")
    op.drop_column("materials", "rag_state")
    op.drop_index("ix_rag_chunks_group", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_material", table_name="rag_chunks")
    op.drop_index("uq_rag_chunks_version_ord", table_name="rag_chunks")
    op.drop_table("rag_chunks")
    op.drop_index("uq_rag_group_configs_group", table_name="rag_group_configs")
    op.drop_table("rag_group_configs")
