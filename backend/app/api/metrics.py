# Метрики HTTP API (NFR-019, HLD §8.3 «Приложение»): счётчик запросов со
# статусами, латентность по маршрутам, активные запросы.
from prometheus_client import Counter, Gauge, Histogram

REQUESTS = Counter(
    "kb_api_requests_total",
    "Запросов к API по методу, маршруту и статусу",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "kb_api_request_latency_seconds",
    "Латентность запросов API (сек)",
    ["method", "path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
IN_PROGRESS = Gauge(
    "kb_api_requests_in_progress",
    "Обрабатываемых запросов прямо сейчас",
    ["method"],
)


def observe(method: str, path: str, status: int, seconds: float) -> None:
    REQUESTS.labels(method=method, path=path, status=str(status)).inc()
    LATENCY.labels(method=method, path=path).observe(seconds)
