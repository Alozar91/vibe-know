"""этап 8: поиск — FTS-поля/индексы materials, аналитика, system_settings (LLD §7, §2.5)

Revision ID: 0008_search
Revises: 0007_stage7
Create Date: 2026-11-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0008_search"
down_revision: str | None = "0007_stage7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- materials.search_lang / search_tsv (LLD §7.1) ---
    op.add_column(
        "materials",
        sa.Column("search_lang", sa.String(20), nullable=False, server_default="russian"),
    )
    # tsvector — не generated (динамическая конфигурация); пересчёт — сервисом
    # и задачей maintenance.fts_rebuild (§7.1, §9)
    op.execute("ALTER TABLE materials ADD COLUMN search_tsv tsvector")

    # --- Индексы (LLD §7.2) ---
    op.execute("CREATE INDEX ix_materials_search_tsv ON materials USING gin (search_tsv)")
    op.execute("CREATE INDEX ix_materials_name_trgm ON materials USING gin (name gin_trgm_ops)")
    op.execute(
        "CREATE INDEX ix_materials_text_trgm ON materials USING gin (text_content gin_trgm_ops)"
    )

    # --- search_events / search_opens / search_analytics (LLD §7.6, FR-127) ---
    op.create_table(
        "search_events",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("query_normalized", sa.Text(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_search_events"),
    )
    op.create_index("ix_search_events_query", "search_events", ["query_normalized"])
    op.create_index("ix_search_events_created", "search_events", ["created_at"])

    op.create_table(
        "search_opens",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("search_event_id", UUID(), nullable=False),
        sa.Column("material_id", UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_search_opens"),
    )
    op.create_foreign_key(
        "fk_search_opens_event_search_events",
        "search_opens", "search_events", ["search_event_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_search_opens_material_materials",
        "search_opens", "materials", ["material_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_search_opens_event", "search_opens", ["search_event_id"])
    op.create_index("ix_search_opens_material", "search_opens", ["material_id"])

    op.create_table(
        "search_analytics",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("zero_result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("open_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name="pk_search_analytics"),
        sa.UniqueConstraint("period_start", "query", name="uq_search_analytics_period_query"),
    )
    op.create_index("ix_search_analytics_period", "search_analytics", ["period_start"])

    # --- system_settings (NFR-020): реестр параметров §2.5 ---
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_system_settings"),
    )

    # Сид параметров §2.5 (значения по умолчанию)
    settings_seed = [
        ("fts_languages", '["russian","english"]', "FR-122: состав конфигураций FTS"),
        ("trgm_similarity_threshold", "0.3", "FR-113, §7.3: порог pg_trgm"),
        ("short_query_min_len", "3", "§7.3: ILIKE-фолбэк коротких запросов"),
        ("page_size", "50", "FR-121: размер страницы списков/поиска"),
        ("analytics_raw_retention_days", "180", "§7.6: хранение raw-событий"),
        ("file_max_size_mb", "100", "FR-031"),
        ("mime_extra", "[]", "FR-056"),
        ("master_change_criterion", '"content"', "FR-038"),
        ("content_downgrade_params", '["file","text"]', "FR-084"),
        ("tags_max", "20", "FR-052"),
        ("attributes_max_per_type", "50", "FR-044"),
        ("name_max_len", "255", "FR-017, FR-027"),
        ("anti_noise_window_minutes", "10", "11.3 (этап 9)"),
        ("digest_interval_minutes", "null", "FR-138: дайджест отключён до настройки"),
        ("audit_retention_days", "null", "FR-141: очистка не выполняется"),
        ("keycloak_sync_interval_minutes", "5", "16.1-118 (этап 10)"),
    ]
    for key, value, description in settings_seed:
        op.execute(
            sa.text(
                "INSERT INTO system_settings (key, value, description) "
                "VALUES (:k, CAST(:v AS jsonb), :d)"
            ).bindparams(k=key, v=value, d=description)
        )

    # --- Первичная пересборка search_tsv (LLD §7.1) ---
    # Веса: A — название, B — значения атрибутов (строковые представления) +
    # названия тегов, C — текстовое представление. Значения справочника/число/
    # дата/url — на MVP в B идут строковые представления; словарные — резолвятся
    # сервисом при записи (update_search_vector); здесь — консервативно.
    op.execute("""
        UPDATE materials m SET search_tsv =
            setweight(to_tsvector('russian', coalesce(m.name, '')), 'A')
            || setweight(to_tsvector('russian', coalesce((
                SELECT string_agg(v.value_string, ' ')
                FROM attribute_values v WHERE v.material_id = m.id
            ), '')), 'B')
            || setweight(to_tsvector('russian', coalesce(m.text_content, '')), 'C')
    """)


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_index("ix_search_analytics_period", table_name="search_analytics")
    op.drop_table("search_analytics")
    op.drop_index("ix_search_opens_material", table_name="search_opens")
    op.drop_index("ix_search_opens_event", table_name="search_opens")
    op.drop_table("search_opens")
    op.drop_index("ix_search_events_created", table_name="search_events")
    op.drop_index("ix_search_events_query", table_name="search_events")
    op.drop_table("search_events")
    op.execute("DROP INDEX IF EXISTS ix_materials_text_trgm")
    op.execute("DROP INDEX IF EXISTS ix_materials_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_materials_search_tsv")
    op.execute("ALTER TABLE materials DROP COLUMN IF EXISTS search_tsv")
    op.drop_column("materials", "search_lang")
