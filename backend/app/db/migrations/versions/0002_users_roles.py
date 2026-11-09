"""этап 2: users, roles, role_permissions, user_roles + сид шаблонов ролей (LLD 2.2, 2.6)

Revision ID: 0002_users_roles
Revises: 0001_foundation
Create Date: 2026-11-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002_users_roles"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("keycloak_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("is_deactivated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_service", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("email_cache", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("keycloak_id", name="uq_users_keycloak_id"),
    )

    op.create_table(
        "roles",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_virtual_all_users", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", UUID(), sa.ForeignKey("roles.id", ondelete="CASCADE", name="fk_role_permissions_role_id_roles"), nullable=False),
        sa.Column("permission", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission", name="pk_role_permissions"),
    )
    op.create_check_constraint(
        "permission_valid",
        "role_permissions",
        "permission IN ('view','create','edit','delete','review','publish','archive','copy','move','download','manage_permissions')",
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", UUID(), sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_user_roles_user_id_users"), nullable=False),
        sa.Column("role_id", UUID(), sa.ForeignKey("roles.id", ondelete="CASCADE", name="fk_user_roles_role_id_roles"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles_pair"),
    )

    # --- Сид: шаблоны ролей (LLD §2.6; 5.2, FR-008) + виртуальная «Все пользователи» (FR-009) ---
    conn = op.get_bind()
    roles = {
        "Читатель": ["view"],
        "Автор": ["view", "create", "edit", "delete"],
        "Рецензент": ["view", "review"],
        "Публикатор": ["view", "publish", "archive"],
    }
    rids: dict[str, str] = {}
    for name, perms in roles.items():
        rid = str(__import__("uuid").uuid4())
        rids[name] = rid
        conn.execute(
            sa.text("INSERT INTO roles (id, name) VALUES (:id, :name)"),
            {"id": rid, "name": name},
        )
        for p in perms:
            conn.execute(
                sa.text("INSERT INTO role_permissions (role_id, permission) VALUES (:rid, :p)"),
                {"rid": rid, "p": p},
            )
    # «Системный администратор» — без снапшотов (суперпользователь по FR-104)
    conn.execute(
        sa.text("INSERT INTO roles (id, name) VALUES (:id, 'Системный администратор')"),
        {"id": str(__import__("uuid").uuid4())},
    )
    # «Все пользователи» — виртуальная роль (FR-009)
    conn.execute(
        sa.text("INSERT INTO roles (id, name, is_virtual_all_users) VALUES (:id, 'Все пользователи', true)"),
        {"id": str(__import__("uuid").uuid4())},
    )


def downgrade() -> None:
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("users")
