"""Этап 11 (NFR-001): fastupdate=off на GIN-индексах поиска

Revision ID: 0010_search_gin_tuning
Revises: 0009_notifications
Create Date: 2026-11-09

Причины (замеры этапа 11, NFR-001): при потоке вставок GIN pending list
(autovacuum_clean) рос до ~800 страниц; поиски вынуждены линейно сканировать
его, а достигший лимита список чистится вставляющим соединением синхронно —
пиковые хвосты p95 поиска. Поток вставок MVP мал (~десятки в час кроме сидов),
прямой апдейт индекса (fastupdate=off) убирает pending list целиком.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0010_search_gin_tuning"
down_revision: str | None = "0009_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER INDEX ix_materials_search_tsv SET (fastupdate = off)")
    op.execute("ALTER INDEX ix_materials_name_trgm SET (fastupdate = off)")
    op.execute("ALTER INDEX ix_materials_text_trgm SET (fastupdate = off)")


def downgrade() -> None:
    op.execute("ALTER INDEX ix_materials_search_tsv SET (fastupdate = on)")
    op.execute("ALTER INDEX ix_materials_name_trgm SET (fastupdate = on)")
    op.execute("ALTER INDEX ix_materials_text_trgm SET (fastupdate = on)")
