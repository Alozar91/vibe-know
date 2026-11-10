"""этап 9: уведомления — notification_events/notifications/trigger_configs (LLD §2.2, §8)

Revision ID: 0009_notifications
Revises: 0008_search
Create Date: 2026-11-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0009_notifications"
down_revision: str | None = "0008_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- notification_events (§8.1): публикуются в транзакции мутации ---
    op.create_table(
        "notification_events",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("material_id", UUID(), nullable=True),
        sa.Column("initiator_user_id", UUID(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),  # JSON
        sa.Column("processed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_notification_events"),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], name="fk_notif_events_material", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["initiator_user_id"], ["users.id"], name="fk_notif_events_initiator", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_notification_events_processed", "notification_events", ["processed", "created_at"])

    # --- notifications (11.3, FR-136–138): доставленные (in-app — строки) ---
    op.create_table(
        "notifications",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("recipient_id", UUID(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("material_id", UUID(), nullable=True),
        sa.Column("channel", sa.String(16), nullable=False, server_default="in_app"),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("email_state", sa.String(16), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("included_in_digest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.ForeignKeyConstraint(
            ["recipient_id"], ["users.id"], name="fk_notifications_recipient", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], name="fk_notifications_material", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_notifications_recipient", "notifications", ["recipient_id", "created_at"])
    op.create_index("ix_notifications_dedup", "notifications", ["dedup_key", "created_at"])

    # --- trigger_configs (11.2, FR-135): одна конфигурация на событие ---
    op.create_table(
        "notification_trigger_configs",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("recipients", sa.Text(), nullable=False),  # JSON
        sa.PrimaryKeyConstraint("id", name="pk_trigger_configs"),
        sa.UniqueConstraint("event_type", name="uq_trigger_configs_event"),
    )

    # --- service_tasks (FR-012, US-004 ш.4): служебные задачи СА ---
    op.create_table(
        "service_tasks",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_service_tasks"),
    )
    op.create_index("ix_service_tasks_state", "service_tasks", ["state", "created_at"])

    # --- Сид предустановленных триггеров (LLD §2.6, FR-135, 16.1-116) ---
    import json

    triggers_seed = [
        # «на проверке» → рецензенты материала (носители права review)
        ("material_sent_to_review", True, [
            {"type": "permission_holder", "permission": "review"},
        ]),
        # «отклонён» → автор
        ("material_rejected", True, [
            {"type": "fact_author"},
        ]),
        # «изменён на ревью» → автор и рецензенты (7.7)
        ("material_changed_on_review", True, [
            {"type": "fact_author"},
            {"type": "permission_holder", "permission": "review"},
        ]),
        # «мастер изменён» → авторы и подписанты подчинённых (FR-135)
        ("master_changed", True, [
            {"type": "fact_author", "scope": "children"},
            {"type": "fact_signatory", "scope": "children"},
        ]),
        # «каскадная архивация» → авторы и подписанты подчинённого
        ("child_auto_archived", True, [
            {"type": "fact_author"},
            {"type": "fact_signatory"},
        ]),
        # «материал заархивирован» → автор и подписант материала (16.1-116)
        ("material_archived", True, [
            {"type": "fact_author"},
            {"type": "fact_signatory"},
        ]),
        # Общий «изменение статуса» — отключён (16.1-89, FR-134)
        ("status_changed", False, [
            {"type": "fact_author"},
        ]),
    ]
    for event_type, enabled, recipients in triggers_seed:
        op.execute(
            sa.text("INSERT INTO notification_trigger_configs (id, event_type, enabled, recipients) "
                    "VALUES (gen_random_uuid(), :et, :en, CAST(:rc AS jsonb))")
            .bindparams(et=event_type, en=enabled, rc=json.dumps(recipients))
        )


def downgrade() -> None:
    op.drop_index("ix_service_tasks_state", table_name="service_tasks")
    op.drop_table("service_tasks")
    op.drop_table("notification_trigger_configs")
    op.drop_index("ix_notifications_dedup", table_name="notifications")
    op.drop_index("ix_notifications_recipient", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_notification_events_processed", table_name="notification_events")
    op.drop_table("notification_events")
