# Контракт чанкера (RAG_DESIGN §4.1). Плагины систему НЕ импортируют:
# duck typing — класс с атрибутом name и методом chunk(text, params).
# Реестр загружает плагины по entry-points group "kb.rag.chunkers".
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class Chunk:
    """Чанк: текст + произвольные метаданные (заголовки, смещения, язык…)."""

    content: str
    meta: dict = field(default_factory=dict)


@runtime_checkable
class Chunker(Protocol):
    """Реестр проверяет name и сигнатуру chunk; остальное — на совести плагина."""

    name: str

    def chunk(self, text: str, params: dict) -> list[Chunk]: ...
