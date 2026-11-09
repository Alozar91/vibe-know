"""этап 1: базовая схема (расширения pg_trgm; остальное — этапы 2-3)

Revision ID: 0001_foundation
Revises:
Create Date: 2026-11-09

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Расширения, требуемые поиском (LLD §7.2: pg_trgm; pgvector — резерв, пост-MVP)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
