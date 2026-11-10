# RAG: пакет векторной индексации (пост-MVP шаг [7]; RAG_DESIGN.md).
# Контракт чанкеров и реестр — §4; конвейер индексации — worker/tasks.py;
# выдача с правами — use_cases/rag/retrieve.py.
from app.rag.base import Chunk, Chunker
from app.rag.registry import available_chunkers, get_chunker

__all__ = ["Chunk", "Chunker", "get_chunker", "available_chunkers"]
