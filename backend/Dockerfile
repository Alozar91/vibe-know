# FastAPI + Celery, Python 3.15 (HLD §4). Зависимости — uv, резолв при сборке
# из pyproject.toml (uv.lock убран: CDN files.pythonhosted.org недоступен
# с сервера развёртывания, см. UV_PYPI_MIRROR в deploy/.env.example).
FROM python:3.15-slim

WORKDIR /app

# uv — стандартный установщик проекта
COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /usr/local/bin/uv

# Слой зависимостей: кэшируется до изменения pyproject.toml
COPY pyproject.toml ./
# UV_PYPI_MIRROR (опционально): зеркало PyPI, если files.pythonhosted.org
# недоступен с сервера (таймауты CDN), например https://pypi.tuna.tsinghua.edu.cn.
# Резолв и скачивание целиком идут с зеркала; пусто — официальный PyPI.
ARG UV_PYPI_MIRROR=""
# Таймауты выше дефолта (10 с соединение / 30 с чтение): медленное, но живое
# зеркало не должно ронять сборку. UV_HTTP_RETRIES поднят с 3 до 5.
RUN if [ -n "$UV_PYPI_MIRROR" ]; then export UV_DEFAULT_INDEX="$UV_PYPI_MIRROR"; fi \
    && export UV_HTTP_CONNECT_TIMEOUT=30 UV_HTTP_TIMEOUT=120 UV_HTTP_RETRIES=5 \
    && uv sync --no-dev --no-install-project

# Код приложения
COPY alembic.ini ./
COPY app/ ./app/

# venv в PATH: plain `python` в контейнере — из окружения проекта
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Миграции применяются при старте api (HLD §8.1); затем uvicorn.
# 4 воркера — HLD §10 («Uvicorn-воркеры + пул соединений PG», вертикальный запас
# single-node под NFR-008); LLD §3.3: кэш прав NOTIFY/LISTEN покрывает несколько
# воркеров (свой LISTEN-поток на выделенном соединении в каждом, TTL 60 с — страховка).
CMD ["sh", "-c", "alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4"]
