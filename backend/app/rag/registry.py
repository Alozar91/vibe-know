# Реестр чанкеров (RAG_DESIGN §4.3, Приложение А): встроенные + entry-points
# группы kb.rag.chunkers (importlib.metadata). Реестр ленивый, один на процесс;
# битый плагин логируется и пропускается (не валит старт).
import logging
from importlib.metadata import entry_points

from app.rag.base import Chunker
from app.rag.chunkers import (
    MarkdownChunker,
    RecursiveChunker,
    SymbolsChunker,
    WholeChunker,
)

log = logging.getLogger(__name__)

# Имя-договорённость: сторонние пакеты объявляют классы в этой группе.
ENTRY_POINT_GROUP = "kb.rag.chunkers"

_REGISTRY: dict[str, Chunker] | None = None


def build_registry() -> dict[str, Chunker]:
    reg: dict[str, Chunker] = {}
    for cls in (WholeChunker, SymbolsChunker, RecursiveChunker, MarkdownChunker):
        reg[cls.name] = cls()

    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:  # py<3.10 синтаксис не нужен, но пусть будет защита
        eps = [ep for ep in entry_points() if ep.group == ENTRY_POINT_GROUP]
    for ep in eps:
        try:
            obj = ep.load()
            name = getattr(obj, "name", ep.name)
            if name in reg:
                log.warning("rag.registry: чанкер %r дубль (%s) — пропущен", name, ep.value)
                continue
            if not callable(getattr(obj, "chunk", None)):
                raise TypeError("нет метода chunk(text, params)")
            reg[name] = obj
            log.info("rag.registry: + внешний чанкер %r (%s)", name, ep.value)
        except Exception:
            log.exception("rag.registry: чанкер %s не загрузился", ep.value)
    return reg


def get_registry() -> dict[str, Chunker]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_registry()
    return _REGISTRY


def get_chunker(name: str) -> Chunker | None:
    return get_registry().get(name)


def available_chunkers() -> list[str]:
    return sorted(get_registry())
