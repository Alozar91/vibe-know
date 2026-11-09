"""этап 4: права (permission_snapshots/entries) + материалы (materials, file_objects, attribute_values, material_tags)

Revision ID: 0004_permissions_materials
Revises: 0003_groups_dicts
Create Date: 2026-11-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0004_permissions_materials"
down_revision: str | None = "0003_groups_dicts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CHECK «ровно одно из пяти значений NOT NULL» (LLD §2.2 attribute_values)
_ONE_VALUE_CHECK = (
    "(CASE WHEN value_string IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN value_number IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN value_date IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN value_url IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN dictionary_value_id IS NULL THEN 0 ELSE 1 END) = 1"
)


def upgrade() -> None:
    op.create_table(
        "permission_snapshots",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("object_type", sa.String(16), nullable=False),
        sa.Column("object_id", UUID(), nullable=False),
        sa.Column("role_id", UUID(), nullable=True),
        sa.Column("created_by", UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_permission_snapshots"),
    )
    op.create_foreign_key(
        "fk_permission_snapshots_role_id_roles", "permission_snapshots", "roles",
        ["role_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_permission_snapshots_created_by_users", "permission_snapshots", "users",
        ["created_by"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_snapshots_object", "permission_snapshots", ["object_type", "object_id"])

    op.create_table(
        "permission_entries",
        sa.Column("snapshot_id", UUID(), nullable=False),
        sa.Column("permission", sa.String(32), nullable=False),
        sa.Column("state", sa.String(8), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id", "permission", name="pk_permission_entries"),
    )
    op.create_foreign_key(
        "fk_permission_entries_snapshot_id_permission_snapshots", "permission_entries",
        "permission_snapshots", ["snapshot_id"], ["id"], ondelete="CASCADE",
    )

    op.create_table(
        "file_objects",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("cas_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("ref_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("scan_state", sa.String(16), nullable=False, server_default="ready"),
        sa.Column("pdf_state", sa.String(16), nullable=False, server_default="none"),
        sa.Column("pdf_cas_key", sa.Text(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_file_objects"),
        sa.UniqueConstraint("cas_key", name="uq_file_objects_cas_key"),
    )
    op.create_index("ix_file_objects_cas", "file_objects", ["cas_key"])

    op.create_table(
        "materials",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("group_id", UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("type_id", UUID(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("master_id", UUID(), nullable=True),
        sa.Column("author_id", UUID(), nullable=False),
        sa.Column("signatory_id", UUID(), nullable=True),
        sa.Column("signatory_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_editor_id", UUID(), nullable=False),
        sa.Column("current_file_id", UUID(), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("text_out_of_sync", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_materials"),
    )
    op.create_foreign_key("fk_materials_group_id_groups", "materials", "groups", ["group_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_materials_type_id_material_types", "materials", "material_types", ["type_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_materials_master_id_materials", "materials", "materials", ["master_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_materials_author_id_users", "materials", "users", ["author_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_materials_signatory_id_users", "materials", "users", ["signatory_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_materials_last_editor_id_users", "materials", "users", ["last_editor_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_materials_current_file_id_file_objects", "materials", "file_objects", ["current_file_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_materials_group", "materials", ["group_id"])
    op.create_index("ix_materials_author", "materials", ["author_id"])
    op.create_index("ix_materials_status", "materials", ["status"])

    op.create_table(
        "attribute_values",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("material_id", UUID(), nullable=False),
        sa.Column("attribute_id", UUID(), nullable=False),
        sa.Column("value_string", sa.Text(), nullable=True),
        sa.Column("value_number", sa.Numeric(), nullable=True),
        sa.Column("value_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("value_url", sa.Text(), nullable=True),
        sa.Column("dictionary_value_id", UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_attribute_values"),
        sa.CheckConstraint(_ONE_VALUE_CHECK, name="ck_attribute_values_one_value"),
    )
    op.create_foreign_key("fk_attribute_values_material_id_materials", "attribute_values", "materials", ["material_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_attribute_values_attribute_id_attributes", "attribute_values", "attributes", ["attribute_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_attribute_values_dictionary_value_id_dictionary_values", "attribute_values", "dictionary_values", ["dictionary_value_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_attribute_values_material", "attribute_values", ["material_id"])

    op.create_table(
        "material_tags",
        sa.Column("material_id", UUID(), nullable=False),
        sa.Column("tag_id", UUID(), nullable=False),
        sa.PrimaryKeyConstraint("material_id", "tag_id", name="pk_material_tags"),
        sa.UniqueConstraint("material_id", "tag_id", name="uq_material_tags_pair"),
    )
    op.create_foreign_key("fk_material_tags_material_id_materials", "material_tags", "materials", ["material_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_material_tags_tag_id_tags", "material_tags", "tags", ["tag_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_material_tags_tag", "material_tags", ["tag_id"])


def downgrade() -> None:
    op.drop_index("ix_material_tags_tag", table_name="material_tags")
    op.drop_table("material_tags")
    op.drop_index("ix_attribute_values_material", table_name="attribute_values")
    op.drop_table("attribute_values")
    op.drop_index("ix_materials_status", table_name="materials")
    op.drop_index("ix_materials_author", table_name="materials")
    op.drop_index("ix_materials_group", table_name="materials")
    op.drop_table("materials")
    op.drop_index("ix_file_objects_cas", table_name="file_objects")
    op.drop_table("file_objects")
    op.drop_table("permission_entries")
    op.drop_index("ix_snapshots_object", table_name="permission_snapshots")
    op.drop_table("permission_snapshots")
