# Точка входа worker-контейнера: Celery-процесс + экспозер метрик :9808 (LLD §9).
# Задачи — этапы 6/9/10; на этапе 1 воркер поднимается пустым (готовность инфраструктуры).
import threading

from prometheus_client import start_http_server

from app.logging import configure_logging, get_logger
from app.worker import celery_app

log = get_logger(__name__)


def _serve_metrics() -> None:
    start_http_server(9808)


def main() -> None:
    from app.config import get_settings

    settings = get_settings()
    configure_logging(settings.log_level)
    log.info("worker.starting", queues=["default"])

    threading.Thread(target=_serve_metrics, daemon=True).start()

    celery_app.worker_main(
        [
            "worker",
            "--loglevel=INFO",
            "--concurrency=2",
        ]
    )


if __name__ == "__main__":
    main()
