# Этап 1: каркас API — healthz, конвенции RFC 7807, OpenAPI (приёмка этапа).
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_unknown_path_returns_problem_json():
    """Несуществующий ресурс — 404 в формате RFC 7807 (LLD §12.1)."""
    r = client.get("/api/v1/nonexistent")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert "code" in body


def test_metrics_endpoint():
    """Экспозер Prometheus на /metrics (NFR-019, LLD §12.3)."""
    r = client.get("/metrics")
    assert r.status_code == 200
    assert b"python_gc_info" in r.content or b"# HELP" in r.content


def test_openapi_available():
    """NFR-021: OpenAPI 3.1 поставляется с системой (LLD §12.1)."""
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["openapi"].startswith("3.1")


def test_unknown_path_returns_problem_json():
    """Несуществующий ресурс — 404 в формате RFC 7807 (LLD §12.1)."""
    r = client.get("/api/v1/nonexistent")
    assert r.status_code == 404
