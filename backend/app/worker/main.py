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

    # Reconcile очереди (LLD §9): queued-задачи из БД перезапускаются в брокер
    # (постановка до коммита/сбой брокера/рестарт worker — task не потерян).
    def _reconcile():
        import time

        for attempt in range(10):
            try:
                time.sleep(3)
                from app.worker.tasks import files_reconcile

                # Прямой вызов тела задачи (без Celery-обёртки apply())
                res = files_reconcile.run()
                if res.get("restarted"):
                    log.info("worker.reconcile", restarted=res["restarted"])
                return
            except Exception as e:  # noqa: BLE001 — брокер ещё не готов
                log.warning("worker.reconcile.retry", attempt=attempt, error=str(e))

    threading.Thread(target=_reconcile, daemon=True).start()

    threading.Thread(target=_serve_metrics, daemon=True).start()

    celery_app.worker_main(
        [
            "worker",
            "--loglevel=INFO",
            "--concurrency=2",
            # Beat встроен в worker (single-node, §9): расписания dispatch ≤15 с,
            # digest, ежедневные maintenance (этап 10)
            "--beat",
        ]
    )


if __name__ == "__main__":
    main()
