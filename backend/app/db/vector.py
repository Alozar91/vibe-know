# Тип pgvector для SQLAlchemy. PostgreSQL — столбец vector(dim);
# SQLite (pytest) — TEXT-заглушка (динамическая типизация), векторные
# ветки поиска на SQLite не выполняются (как TSVector, LLD §7.1).
from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType):
    """rag_chunks.embedding — vector(RAG_EMBEDDING_DIM), pgvector."""

    cached_ok = True

    def __init__(self, dim: int | None = None):
        self.dim = dim

    def get_col_spec(self) -> str:
        return f"vector({self.dim})" if self.dim else "vector"
