"""этап 3: groups (materialized path), types/attributes/dictionaries/tags + сиды §2.6

Revision ID: 0003_groups_dicts
Revises: 0002_users_roles
Create Date: 2026-11-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003_groups_dicts"
down_revision: str | None = "0002_users_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- ENUM attr_value_type (LLD §2.1); material_status/permission_code — сидятся как CHECK/varchar в 0002 ---
    op.execute("CREATE TYPE attr_value_type AS ENUM ('string','number','date','url','dictionary')")
    op.execute("CREATE TYPE material_status AS ENUM ('draft','in_review','approved','published','archived')")
    op.execute("CREATE TYPE event_type AS ENUM ("
               "'material_sent_to_review','material_rejected','material_archived',"
               "'child_auto_archived','master_changed','material_changed_on_review',"
               "'status_changed','file_blocked')")
    op.execute("CREATE TYPE recipient_type AS ENUM ("
               "'role','fact_author','fact_signatory','fact_last_editor','permission_holder')")

    op.create_table(
        "groups",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("parent_id", UUID(), sa.ForeignKey("groups.id", ondelete="RESTRICT", name="fk_groups_parent_id_groups"), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_groups"),
    )
    op.create_index("ix_groups_parent_id", "groups", ["parent_id"])
    op.create_index("ix_groups_path", "groups", ["path"])
    op.create_index("ix_groups_normalized", "groups", ["parent_id", "normalized_name"])

    op.create_table(
        "material_types",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_material_types"),
        sa.UniqueConstraint("name", name="uq_material_types_name"),
    )

    op.create_table(
        "dictionaries",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dictionaries"),
        sa.UniqueConstraint("name", name="uq_dictionaries_name"),
    )

    op.create_table(
        "dictionary_values",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("dictionary_id", UUID(), sa.ForeignKey("dictionaries.id", ondelete="CASCADE", name="fk_dictionary_values_dictionary_id_dictionaries"), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dictionary_values"),
        sa.UniqueConstraint("dictionary_id", "value", name="uq_dictionary_values_pair"),
    )

    op.create_table(
        "attributes",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # В проде — attr_value_type ENUM; в тестах SQLite миграция не исполняется (create_all), здесь строка
        sa.Column("value_type", sa.String(16), nullable=False),
        sa.Column("is_multivalue", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("dictionary_id", UUID(), sa.ForeignKey("dictionaries.id", ondelete="RESTRICT", name="fk_attributes_dictionary_id_dictionaries"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_attributes"),
        sa.UniqueConstraint("name", name="uq_attributes_name"),
        sa.CheckConstraint("(value_type != 'dictionary') OR (dictionary_id IS NOT NULL)", name="ck_attributes_dictionary_attr_requires_dict"),
    )

    op.create_table(
        "attribute_type_bindings",
        sa.Column("type_id", UUID(), sa.ForeignKey("material_types.id", ondelete="CASCADE", name="fk_attribute_type_bindings_type_id_material_types"), nullable=False),
        sa.Column("attribute_id", UUID(), sa.ForeignKey("attributes.id", ondelete="CASCADE", name="fk_attribute_type_bindings_attribute_id_attributes"), nullable=False),
        sa.PrimaryKeyConstraint("type_id", "attribute_id", name="pk_attribute_type_bindings"),
    )

    op.create_table(
        "tags",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tags"),
        sa.UniqueConstraint("name", name="uq_tags_name"),
    )

    # --- Сид: матрица переходов (LLD §2.6, FR-071/073) + триггеры уведомлений (FR-135, 16.1-116) ---
    # Таблицы transition_rules/transition_rule_permissions/notification_triggers — этапы 5/9
    # (сюда не входят; сид их состава выполняется в миграциях соответствующих этапов).
    # Сиды каталога прав/статусов/ролей выполнены в 0002 (role_permissions = каталог 11 прав).

    # Проверка: каталог прав 11 значений уже покрыт CHECK-ограничением 0002
    # (permission IN (...)) — FR-106.


def downgrade() -> None:
    op.drop_table("tags")
    op.drop_table("attribute_type_bindings")
    op.drop_table("attributes")
    op.drop_table("dictionary_values")
    op.drop_table("dictionaries")
    op.drop_table("material_types")
    op.drop_index("ix_groups_normalized", table_name="groups")
    op.drop_index("ix_groups_path", table_name="groups")
    op.drop_index("ix_groups_parent_id", table_name="groups")
    op.drop_table("groups")
    op.execute("DROP TYPE IF EXISTS recipient_type")
    op.execute("DROP TYPE IF EXISTS event_type")
    op.execute("DROP TYPE IF EXISTS material_status")
    op.execute("DROP TYPE IF EXISTS attr_value_type")
