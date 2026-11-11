# Embedding-клиент (RAG_DESIGN §6): OpenAI-совместимый POST /v1/embeddings.
# Пачки по KB_RAG_EMBEDDING_BATCH (32–64); ретраи — по правилам Gotenberg/SMTP
# (LLD §9): экспоненциально, ограничение — max_retries задачи Celery.
# Совместимость обязательна: OpenAI, vLLM, Ollama, Azure OpenAI.
import logging

import httpx

log = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Сбой провайдера эмбеддингов (после ретраев — задача помечается failed)."""


class EmbeddingClient:
    """Тонкий синхронный клиент /embeddings (httpx, как Gotenberg-клиент)."""

    def __init__(self, settings, timeout: float | None = None):
        self.base_url = (settings.rag_embedding_base_url or "").rstrip("/")
        self.api_key = settings.rag_embedding_api_key or ""
        self.model = settings.rag_embedding_model
        self.dim = int(settings.rag_embedding_dim)
        self.batch = max(1, int(settings.rag_embedding_batch))
        self.timeout = float(timeout if timeout is not None else settings.rag_embedding_timeout)

    @property
    def enabled(self) -> bool:
        """Конфиг заполнен (base_url) — конвейер работает; иначе «off»."""
        return bool(self.base_url)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Векторы для пачки текстов; порядок ответа = порядку входа.

        Разбиение на пачки — внутри; соединяет результаты подряд.
        """
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            out.extend(self._embed_batch(texts[i:i + self.batch]))
        return out

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.base_url}/embeddings"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "input": texts}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise EmbeddingError(
                f"embedding-провайдер вернул {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        try:
            rows = sorted(data["data"], key=lambda r: r["index"])
            vecs = [list(map(float, r["embedding"])) for r in rows]
        except (KeyError, TypeError, ValueError) as e:
            raise EmbeddingError(f"неожиданный ответ /embeddings: {e}") from e
        if len(vecs) != len(texts):
            raise EmbeddingError(
                f"провайдер вернул {len(vecs)} векторов на {len(texts)} текстов"
            )
        got_dim = len(vecs[0]) if vecs else self.dim
        if got_dim != self.dim:
            raise EmbeddingError(
                f"размерность провайдера {got_dim} != KB_RAG_EMBEDDING_DIM={self.dim}; "
                "смена модели/размерности требует миграции и полного переиндекса "
                "(RAG_DESIGN §2)"
            )
        return vecs

    def probe(self) -> dict:
        """POST /admin/rag/test-connection: доступность + фактическая размерность."""
        vec = self.embed(["проверка связи"])
        return {"ok": True, "model": self.model, "dim": len(vec[0]) if vec else 0}
