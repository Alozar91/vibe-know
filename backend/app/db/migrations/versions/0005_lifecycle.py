"""этап 5: жизненный цикл — transition_rules, transition_rule_permissions, status_log, audit_entries + сид матрицы (LLD §2.2, §2.6, §4.1, §11)

Revision ID: 0005_lifecycle
Revises: 0004_permissions_materials
Create Date: 2026-11-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0005_lifecycle"
down_revision: str | None = "0004_permissions_materials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Матрица переходов §2.6 (FR-071, FR-073): from_status NULL = «*» (любой,
# кроме «Архива»); is_protected — защищённые системные переходы (FR-073).
_TRANSITION_RULES = [
    # (from_status, to_status, is_protected, permissions)
    ("draft", "in_review", False, ["edit"]),
    ("in_review", "approved", False, ["review"]),
    ("in_review", "draft", False, ["review", "edit"]),
    ("approved", "draft", False, ["review"]),
    ("approved", "published", True, ["publish"]),
    (None, "archived", True, ["archive"]),
]


def upgrade() -> None:
    op.create_table(
        "transition_rules",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("is_protected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_transition_rules"),
    )
    op.create_index(
        "ix_transition_rules_pair",
        "transition_rules",
        ["from_status", "to_status"],
        unique=True,
        postgresql_where="from_status IS NULL OR from_status <> 'archived'",
    )

    op.create_table(
        "transition_rule_permissions",
        sa.Column("rule_id", UUID(), nullable=False),
        sa.Column("permission", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("rule_id", "permission", name="pk_transition_rule_permissions"),
    )
    op.create_foreign_key(
        "fk_transition_rule_permissions_rule_id_transition_rules",
        "transition_rule_permissions", "transition_rules",
        ["rule_id"], ["id"], ondelete="CASCADE",
    )

    op.create_table(
        "status_log",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("material_id", UUID(), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_status_log"),
    )
    op.create_foreign_key("fk_status_log_material_id_materials", "status_log", "materials", ["material_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_status_log_user_id_users", "status_log", "users", ["user_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_status_log_material", "status_log", ["material_id"])
    op.create_index("ix_status_log_user", "status_log", ["user_id"])

    op.create_table(
        "audit_entries",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_user_id", UUID(), nullable=True),
        sa.Column("actor_is_service", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", UUID(), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_entries"),
    )
    op.create_foreign_key("fk_audit_entries_actor_user_id_users", "audit_entries", "users", ["actor_user_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_audit_entries_object", "audit_entries", ["object_type", "object_id"])
    op.create_index("ix_audit_entries_occurred_at", "audit_entries", ["occurred_at"])

    # --- Сид: матрица переходов (LLD §2.6; FR-071/073) ---
    conn = op.get_bind()
    for from_status, to_status, is_protected, perms in _TRANSITION_RULES:
        rid = str(__import__("uuid").uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO transition_rules (id, from_status, to_status, is_protected)"
                " VALUES (:id, :fs, :ts, :prot)"
            ),
            {"id": rid, "fs": from_status, "ts": to_status, "prot": is_protected},
        )
        for p in perms:
            conn.execute(
                sa.text(
                    "INSERT INTO transition_rule_permissions (rule_id, permission)"
                    " VALUES (:rid, :p)"
                ),
                {"rid": rid, "p": p},
            )


def downgrade() -> None:
    op.drop_table("audit_entries")
    op.drop_index("ix_status_log_user", table_name="status_log")
    op.drop_index("ix_status_log_material", table_name="status_log")
    op.drop_table("status_log")
    op.drop_table("transition_rule_permissions")
    op.drop_index("ix_transition_rules_pair", table_name="transition_rules")
    op.drop_table("transition_rules")
