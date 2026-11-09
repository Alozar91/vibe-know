"""этап 7: мастер-подчинённый — comments (LLD §2.2/§2.4), ограничения master_id (LLD §2.3)

Revision ID: 0007_stage7
Revises: 0006_files_versions
Create Date: 2026-11-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0007_stage7"
down_revision: str | None = "0006_files_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # comments (LLD §2.2, 7.6, FR-096–098): append-only (без UPDATE/DELETE)
    op.create_table(
        "comments",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("material_id", UUID(), nullable=False),
        sa.Column("author_id", UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_comments"),
    )
    op.create_foreign_key(
        "fk_comments_material_id_materials",
        "comments", "materials", ["material_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_comments_author_id_users",
        "comments", "users", ["author_id"], ["id"], ondelete="RESTRICT",
    )
    # B-tree по объекту/дате (§2.4): лента комментариев карточки
    op.create_index("ix_comments_material", "comments", ["material_id", "created_at"])
    op.create_index("ix_comments_author", "comments", ["author_id"])

    # CHECK master_id <> id (LLD §2.3, FR-032) — в 0004 не создавался
    op.create_check_constraint(
        "ck_materials_master_not_self", "materials", "master_id IS NULL OR master_id <> id"
    )
    # B-tree master_id (§2.4): список подчинённых, валидаторы
    op.create_index("ix_materials_master", "materials", ["master_id"])

    # «Мастер без собственного мастера» (LLD §2.3, 4.4): триггер на
    # вставку/обновление (CHECK с подзапросом недопустим). Дублируется
    # инвариантом уровня сервиса (use-cases этапа 7).
    op.execute("""
        CREATE OR REPLACE FUNCTION fn_materials_master_flat() RETURNS trigger AS $$
        BEGIN
            IF NEW.master_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM materials m WHERE m.id = NEW.master_id AND m.master_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION ' subordinate-of-subordinate forbidden (FR-032) '
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_materials_master_flat
        BEFORE INSERT OR UPDATE OF master_id ON materials
        FOR EACH ROW EXECUTE FUNCTION fn_materials_master_flat();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_materials_master_flat ON materials")
    op.execute("DROP FUNCTION IF EXISTS fn_materials_master_flat()")
    op.drop_index("ix_materials_master", table_name="materials")
    op.drop_constraint("ck_materials_master_not_self", "materials", type_="check")
    op.drop_index("ix_comments_author", table_name="comments")
    op.drop_index("ix_comments_material", table_name="comments")
    op.drop_table("comments")
