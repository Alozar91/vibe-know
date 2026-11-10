# Конфигурация приложения (12-Factor: окружение Compose → .env, HLD §3.2).
# pydantic-settings: префикс KB_, секреты — не в коде и не в репозитории.
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KB_", env_file=".env", extra="ignore")

    # Приложение (KB_LOG_LEVEL)
    app_name: str = "Корпоративная база знаний"
    log_level: str = "INFO"

    # PostgreSQL (HLD §3.2): единая БД kb; БД keycloak — отдельная база того же экземпляра
    database_url: str = "postgresql+psycopg://kb:change-me@localhost:5432/kb"

    # Valkey (брокер Celery + кэш, LLD §9)
    redis_url: str = "redis://localhost:6379/0"

    # Silo (S3 API, CAS — этап 6)
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "kb-files"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Gotenberg (конвертация офисных форматов, LLD §6.3)
    gotenberg_url: str = "http://localhost:3000"

    # Keycloak (OIDC, introspection — LLD §10)
    oidc_issuer: str = "http://localhost:8080/realms/kb"
    oidc_introspection_url: str = "http://localhost:8080/realms/kb/protocol/openid-connect/token/introspect"
    oidc_client_id: str = "kb-api"
    oidc_client_secret: str = ""

    # CORS/dev
    frontend_url: str = "http://localhost"

    # Тестовая регистрация с выбором роли (НЕ для продуктива): по умолчанию выключена.
    test_registration: bool = False

    # RAG (пост-MVP шаг [7], RAG_DESIGN §6): OpenAI-совместимый /v1/embeddings.
    # base_url — без /v1 на конце (клиент добавляет сам); api_key пустой —
    # RAG-конвейер в «off» (задачи не эмбеддят, хуки не ставят pending).
    rag_embedding_base_url: str = ""
    rag_embedding_api_key: str = ""
    rag_embedding_model: str = "text-embedding-3-small"
    rag_embedding_dim: int = 1536
    rag_embedding_timeout: float = 30.0
    rag_embedding_batch: int = 32  # чанков в одном запросе (§6: 32–64)


@lru_cache
def get_settings() -> Settings:
    return Settings()
