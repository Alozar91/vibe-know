# Встроенные чанкеры (RAG_DESIGN §4.2). Контракт — app/rag/base.py.
# Имена — значения настройки rag_group_configs.chunker; параметры — params JSONB.
import hashlib
import re

from app.rag.base import Chunk


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class WholeChunker:
    """Весь текст одним чанком; длиннее max_len — обрезается (последний чанк)."""

    name = "whole"

    def chunk(self, text: str, params: dict) -> list[Chunk]:
        max_len = max(1, int(params.get("max_len", 8000)))
        t = text.strip()
        if not t:
            return []
        if len(t) <= max_len:
            return [Chunk(t, {"chunker": self.name, "offset": 0})]
        return [Chunk(t[:max_len], {"chunker": self.name, "offset": 0, "truncated": True})]


class SymbolsChunker:
    """Окно по символам с перекрытием (size, overlap)."""

    name = "symbols"

    def chunk(self, text: str, params: dict) -> list[Chunk]:
        size = max(64, int(params.get("size", 1000)))
        overlap = min(max(0, int(params.get("overlap", size // 5))), size - 1)
        step = size - overlap
        t = text.strip()
        if not t:
            return []
        out = []
        for start in range(0, len(t), step):
            piece = t[start:start + size].strip()
            if piece:
                out.append(Chunk(piece, {"chunker": self.name, "offset": start}))
        return out


class RecursiveChunker:
    """Заголовки → абзацы → предложения: слияние до size, разрезание при переполнении.

    Универсальный дефолт для не-markdown текста.
    """

    name = "recursive"

    _SEP = re.compile(r"\n{2,}")

    def chunk(self, text: str, params: dict) -> list[Chunk]:
        size = max(128, int(params.get("size", 1200)))
        overlap = max(0, int(params.get("overlap", 120)))
        out: list[Chunk] = []
        pos = 0
        for block in self._SEP.split(text):
            block = block.strip()
            if not block:
                continue
            start = text.find(block, pos)
            start = start if start >= 0 else pos
            pos = start + len(block)
            self._emit(out, block, start, size, overlap)
        # Слияние короткого хвоста с предыдущим чанком (границы абзацев уже не важны)
        if len(out) > 1 and len(out[-1].content) < size // 4:
            prev = out[-2]
            if len(prev.content) + len(out[-1].content) + 2 <= size:
                merged = out.pop()
                prev.content += "\n\n" + merged.content
        return out

    def _emit(self, out: list[Chunk], block: str, start: int, size: int, overlap: int) -> None:
        if len(block) <= size:
            if out and len(out[-1].content) + 2 + len(block) <= size \
                    and out[-1].meta.get("merged") is not False:
                # Слияние с предыдущим, пока помещается (абзацы одного потока)
                prev = out[-1]
                prev.content += "\n\n" + block
            else:
                out.append(Chunk(block, {"chunker": self.name, "offset": start}))
            return
        # Переполнение: резать по предложениям; слияние не продолжаем
        if out:
            out[-1].meta["merged"] = False
        for piece, off in self._split_sentences(block, size, overlap):
            out.append(Chunk(piece, {"chunker": self.name, "offset": off}))

    def _split_sentences(self, block: str, size: int, overlap: int) -> list[tuple[str, int]]:
        sentences = re.split(r"(?<=[.!?…])\s+", block)
        pieces: list[tuple[str, int]] = []
        cur = ""
        cur_start = 0
        pos = 0
        for s in sentences:
            if cur and len(cur) + 1 + len(s) > size:
                pieces.append((cur, cur_start))
                tail = cur[-overlap:] if overlap else ""
                cur_start = max(0, pos - len(tail))
                cur = (tail + " " + s).strip()
            else:
                cur = (cur + " " + s).strip() if cur else s
                if not pieces and not cur_start:
                    cur_start = pos
            pos += len(s) + 1
        if cur:
            pieces.append((cur, cur_start))
        return pieces


class MarkdownChunker:
    """По заголовкам Markdown (#…); meta.heading_path — путь заголовков для цитат.

    Слишком длинные секции добиваются по абзацам (слияние до max_len).
    """

    name = "markdown"

    _HDR = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)

    def chunk(self, text: str, params: dict) -> list[Chunk]:
        max_len = max(128, int(params.get("max_len", 1600)))
        min_len = max(0, int(params.get("min_len", 80)))

        # Секции: (heading_path, start) + конец следующего заголовка
        hits = list(self._HDR.finditer(text))
        sections: list[tuple[list[str], int]] = []
        if not hits:
            sections.append(([], 0))
        else:
            if hits[0].start() > 0:  # преамбула до первого заголовка
                sections.append(([], 0))
            stack: list[tuple[int, str]] = []  # (level, title) — открытая иерархия
            for h in hits:
                level = len(h.group(1))
                title = h.group(2).strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                sections.append(([t for _, t in stack], h.start()))

        out: list[Chunk] = []
        for i, (path, start) in enumerate(sections):
            # Конец секции: старт следующей секции или конец текста
            end = sections[i + 1][1] if i + 1 < len(sections) else len(text)
            piece = text[start:end].strip()
            if not piece:
                continue
            if len(piece) <= max_len:
                out.append(Chunk(piece, self._meta(path, start)))
            else:
                # Длинная секция: абзацы, слияние до max_len
                buf = ""
                buf_start = start
                for para in re.split(r"\n{2,}", piece):
                    if buf and len(buf) + 2 + len(para) > max_len:
                        out.append(Chunk(buf.strip(), self._meta(path, buf_start)))
                        buf, buf_start = para, start + piece.find(para)
                    else:
                        buf = (buf + "\n\n" + para).strip()
                if buf.strip():
                    out.append(Chunk(buf.strip(), self._meta(path, buf_start)))
        # Слишком короткий БЕЗЫМЯННЫЙ хвост (преамбула/хвост без заголовка)
        # присоединяем к соседнему — шум одиночных строк. Секции с заголовком
        # не склеиваем: заголовок — смысловая граница (цитаты в ответах LLM).
        if min_len and len(out) > 1 and len(out[-1].content) < min_len \
                and not out[-1].meta["heading_path"] and not out[-2].meta["heading_path"]:
            prev = out[-2]
            if len(prev.content) + len(out[-1].content) <= max_len * 2:
                tail = out.pop()
                prev.content += "\n\n" + tail.content
        return out

    def _meta(self, heading_path: list[str], offset: int) -> dict:
        return {"chunker": self.name, "heading_path": heading_path, "offset": offset}
