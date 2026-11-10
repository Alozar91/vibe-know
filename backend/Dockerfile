# FastAPI + Celery, Python 3.15 (HLD §4). Зависимости — uv (uv.lock).
FROM python:3.15-slim

WORKDIR /app

# uv — стандартный установщик проекта
COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /usr/local/bin/uv

# Слой зависимостей: кэшируется до изменения uv.lock
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

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
