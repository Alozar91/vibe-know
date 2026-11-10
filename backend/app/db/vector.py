# Тип pgvector для SQLAlchemy. PostgreSQL — столбец vector(dim);
# SQLite (pytest) — TEXT-заглушка с JSON-сериализацией (динамическая типизация),
# векторные ветки поиска на SQLite не выполняются (как TSVector, LLD §7.1).
import json

from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType):
    """rag_chunks.embedding — vector(RAG_EMBEDDING_DIM), pgvector."""

    cache_ok = True  # dim неизменяем после создания — ключ кэша безопасен

    def __init__(self, dim: int | None = None):
        self.dim = dim

    def get_col_spec(self) -> str:
        return f"vector({self.dim})" if self.dim else "vector"

    def bind_processor(self, dialect):
        if dialect.name == "postgresql":
            # psycopg3 сам сериализует list → vector при известном типе столбца;
            # строковое представление '[1,2,3]' надёжнее (текстовый литерал vector)
            def process(value):
                if value is None:
                    return None
                if isinstance(value, (list, tuple)):
                    return "[" + ",".join(repr(float(x)) for x in value) + "]"
                return value

            return process

        def process_sqlite(value):
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                return json.dumps(list(value))
            return value

        return process_sqlite

    def result_processor(self, dialect, coltype):
        if dialect.name == "postgresql":
            return None  # psycopg возвращает numpy-подобный vector — оставляем как есть

        import json as _json

        def process_sqlite(value):
            if value is None or isinstance(value, list):
                return value
            try:
                return _json.loads(value)
            except (ValueError, TypeError):
                return value

        return process_sqlite

