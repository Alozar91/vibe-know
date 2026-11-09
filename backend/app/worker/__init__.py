# Celery-приложение worker (LLD §9: брокер — Valkey, источник истины — system_tasks, этап 10).
# Обработчики задач добавляются по этапам 6 (files.scan, files.convert), 9 (notifications.*),
# 10 (maintenance.*, keycloak.sync).
from celery import Celery

from app.config import get_settings


def make_celery() -> Celery:
    settings = get_settings()
    app = Celery(
        "kb",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=["app.worker.tasks"],
    )
    app.conf.update(
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_time_limit=3600,
        timezone="UTC",
    )
    return app


celery_app = make_celery()
