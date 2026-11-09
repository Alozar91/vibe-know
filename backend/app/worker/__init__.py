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
        # Расписания (LLD §9): dispatch ≤ 15 с (NFR-007), digest — ежечасный
        # запуск с проверкой digest_interval_minutes внутри (§8.2);
        # ежедневные maintenance — этап 10.
        beat_schedule={
            "notifications-dispatch": {
                "task": "notifications.dispatch",
                "schedule": 15.0,
            },
            "notifications-digest": {
                "task": "notifications.digest",
                "schedule": 3600.0,
            },
        },
    )
    return app


celery_app = make_celery()
