"""этап 6: файлы и версии — material_versions (LLD §5.1), system_tasks (LLD §2.2, §9)

Revision ID: 0006_files_versions
Revises: 0005_lifecycle
Create Date: 2026-11-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0006_files_versions"
down_revision: str | None = "0005_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # material_versions (LLD §5.1, FR-144–148): снапшот версии материала
    op.create_table(
        "material_versions",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("material_id", UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("author_id", UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_material_versions"),
    )
    op.create_foreign_key(
        "fk_material_versions_material_id_materials",
        "material_versions", "materials", ["material_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_material_versions_author_id_users",
        "material_versions", "users", ["author_id"], ["id"], ondelete="RESTRICT",
    )
    # UNIQUE (material_id, number) — номер с 1 внутри материала (§2.4)
    op.create_index(
        "uq_material_versions_number",
        "material_versions", ["material_id", "number"], unique=True,
    )

    # system_tasks (LLD §2.2, §9, NFR-014): источник истины состояний задач
    op.create_table(
        "system_tasks",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("object_type", sa.String(16), nullable=True),
        sa.Column("object_id", UUID(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_system_tasks"),
    )
    # B-tree (task_type, state) — мониторинг глубины/возраста очередей (NFR-019)
    op.create_index("ix_system_tasks_type_state", "system_tasks", ["task_type", "state"])
    op.create_index("ix_system_tasks_object", "system_tasks", ["object_type", "object_id"])


def downgrade() -> None:
    op.drop_index("ix_system_tasks_object", table_name="system_tasks")
    op.drop_index("ix_system_tasks_type_state", table_name="system_tasks")
    op.drop_table("system_tasks")
    op.drop_index("uq_material_versions_number", table_name="material_versions")
    op.drop_table("material_versions")
