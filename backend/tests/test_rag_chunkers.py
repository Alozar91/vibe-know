# Тесты RAG-чанкеров и реестра (пост-MVP шаг [7], RAG_DESIGN §4).
# Чанкеры — чистые функции (без БД); реестр — встроенные + подмена entry-points.
from app.rag.chunkers import (
    MarkdownChunker,
    RecursiveChunker,
    SymbolsChunker,
    WholeChunker,
    content_hash,
)
from app.rag import registry


class TestWhole:
    def test_empty(self):
        assert WholeChunker().chunk("", {}) == []
        assert WholeChunker().chunk("   \n  ", {}) == []

    def test_single(self):
        out = WholeChunker().chunk("Привет, мир", {})
        assert len(out) == 1 and out[0].content == "Привет, мир"
        assert out[0].meta["chunker"] == "whole"

    def test_truncation(self):
        out = WholeChunker().chunk("x" * 2500, {"max_len": 2000})
        assert len(out) == 1 and len(out[0].content) == 2000
        assert out[0].meta["truncated"] is True


class TestSymbols:
    def test_windows_and_overlap(self):
        text = "".join(str(i % 10) for i in range(2500))  # 2500 символов
        out = SymbolsChunker().chunk(text, {"size": 1000, "overlap": 200})
        assert len(out) == 4  # step 800: 0, 800, 1600, 2400
        # Перекрытие: конец предыдущего == начало следующего минус overlap
        assert out[0].content[-200:] == out[1].content[:200]

    def test_overlap_clamped(self):
        out = SymbolsChunker().chunk("y" * 500, {"size": 200, "overlap": 500})
        assert all(len(c.content) <= 200 for c in out)

    def test_min_size(self):
        # size ниже 64 поднимается до 64 (защита от деградации)
        out = SymbolsChunker().chunk("z" * 300, {"size": 10, "overlap": 0})
        assert all(len(c.content) <= 64 for c in out)


class TestRecursive:
    def test_merges_paragraphs(self):
        text = "Абзац один.\n\nАбзац два.\n\nАбзац три."
        out = RecursiveChunker().chunk(text, {"size": 1000})
        assert len(out) == 1 and "Абзац один" in out[0].content and "Абзац три" in out[0].content

    def test_splits_long_block_by_sentences(self):
        text = ("Предложение номер один. " * 100).strip()  # ~2400 символов
        out = RecursiveChunker().chunk(text, {"size": 600, "overlap": 0})
        assert len(out) >= 4
        assert all(len(c.content) <= 700 for c in out)

    def test_paragraph_boundary_respected(self):
        # size клампится до 128 (минимум): блоки ~100 символов поодиночке
        # помещаются в чанк, вдвоём — нет → граница абзацев соблюдена
        text = ("Первый блок: " + "а" * 96 + ".\n\n"
                "Второй блок: " + "б" * 96 + ".")
        out = RecursiveChunker().chunk(text, {"size": 12})
        assert len(out) == 2
        assert out[0].content.startswith("Первый")
        assert out[1].content.startswith("Второй")


class TestMarkdown:
    TEXT = (
        "# Раздел 1\nТекст первого раздела.\n\n"
        "## Подраздел 1.1\nПодробности подраздела.\n\n"
        "# Раздел 2\nФинальный текст."
    )

    def test_heading_path(self):
        out = MarkdownChunker().chunk(self.TEXT, {})
        paths = [c.meta.get("heading_path") for c in out]
        assert ["Раздел 1"] in paths
        assert ["Раздел 1", "Подраздел 1.1"] in paths
        assert ["Раздел 2"] in paths

    def test_preamble(self):
        out = MarkdownChunker().chunk("Преамбула до заголовка.\n\n" + self.TEXT, {})
        assert out[0].content.startswith("Преамбула")
        assert out[0].meta["heading_path"] == []

    def test_long_section_split(self):
        body = "\n\n".join(f"Абзац {i}. " + "т" * 200 for i in range(10))
        out = MarkdownChunker().chunk("# Заголовок\n\n" + body, {"max_len": 600})
        assert len(out) > 1
        assert all(c.meta["heading_path"] == ["Заголовок"] for c in out)

    def test_no_headings(self):
        out = MarkdownChunker().chunk("Просто текст без разметки.", {})
        assert len(out) == 1 and out[0].meta["heading_path"] == []


class TestRegistry:
    def test_builtin_names(self):
        names = registry.available_chunkers()
        for n in ("whole", "symbols", "recursive", "markdown"):
            assert n in names

    def test_get_unknown(self):
        assert registry.get_chunker("нет-такого") is None

    def test_plugin_via_entry_points(self, monkeypatch):
        """Внешний чанкер: подменяем entry_points (имитация установленного пакета)."""
        class FakeChunker:
            name = "fake_ext"
            def chunk(self, text, params):
                return []

        class FakeEP:
            name = "fake_ext"
            value = "fake_mod:FakeChunker"
            def load(self):
                return FakeChunker()

        def fake_eps(group=None):
            assert group == registry.ENTRY_POINT_GROUP
            return [FakeEP()]

        monkeypatch.setattr(registry, "entry_points", fake_eps)
        monkeypatch.setattr(registry, "_REGISTRY", None)  # сброс кэша
        reg = registry.build_registry()
        assert "fake_ext" in reg and reg["fake_ext"].name == "fake_ext"
        # И встроенные на месте
        assert "markdown" in reg
        monkeypatch.setattr(registry, "_REGISTRY", None)  # не портить другие тесты

    def test_broken_plugin_skipped(self, monkeypatch):
        from importlib.metadata import EntryPoint

        ep = EntryPoint(name="broken", value="no.such.module:Thing", group="kb.rag.chunkers")
        monkeypatch.setattr(registry, "entry_points", lambda group=None: [ep])
        monkeypatch.setattr(registry, "_REGISTRY", None)
        reg = registry.build_registry()
        assert "broken" not in reg and "markdown" in reg
        monkeypatch.setattr(registry, "_REGISTRY", None)


def test_content_hash_stable():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")
    assert len(content_hash("abc")) == 64
