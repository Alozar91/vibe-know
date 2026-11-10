# Экспозер метрик очередей (NFR-019, LLD §9): глубина и возраст очередей из
# system_tasks — источник истины (брокер Valkey — транспорт). Обновление — по
# таймеру (интервал = scrape_interval 15 с); ошибки БД не роняют экспозер.
import threading
import time

from prometheus_client import Gauge, start_http_server

from app.logging import configure_logging, get_logger

log = get_logger(__name__)

# Глубина очереди: задач по типу и состоянию (queued/running/failing)
QUEUE_DEPTH = Gauge(
    "kb_queue_depth",
    "Задач в очереди по типу и состоянию (из system_tasks)",
    ["task_type", "state"],
)
# Возраст старейшей queued-задачи по типу (сек) — рост = застой очереди
QUEUE_AGE = Gauge(
    "kb_queue_age_seconds",
    "Возраст старейшей queued-задачи по типу (из system_tasks)",
    ["task_type"],
)
# Доля ошибок за окно по типу: failed / (failed + done)
QUEUE_ERRORS = Gauge(
    "kb_queue_error_ratio",
    "Доля ошибок задач по типу за последнее окно (из system_tasks)",
    ["task_type"],
)


def _update_metrics() -> None:
    from sqlalchemy import func, select

    from app.db import models
    from app.db.engine import get_session_factory

    session = get_session_factory()()
    try:
        rows = session.execute(
            select(
                models.SystemTask.task_type,
                models.SystemTask.state,
                func.count(models.SystemTask.id),
            ).group_by(models.SystemTask.task_type, models.SystemTask.state)
        ).all()

        # clear() — набор серий (task_type, state) меняется со временем
        QUEUE_DEPTH.clear()
        for task_type, state, cnt in rows:
            QUEUE_DEPTH.labels(task_type=task_type, state=state).set(cnt)

        age_rows = session.execute(
            select(
                models.SystemTask.task_type,
                func.max(
                    func.extract(
                        "epoch",
                        func.now() - models.SystemTask.scheduled_at,
                    )
                ),
            )
            .where(models.SystemTask.state == "queued")
            .group_by(models.SystemTask.task_type)
        ).all()
        QUEUE_AGE.clear()
        for task_type, age in age_rows:
            if age is not None:
                QUEUE_AGE.labels(task_type=task_type).set(float(age))

        # Доля ошибок за окно 24 ч (накопленная за всё время искажает после
        # разовых сбоев): failed / (failed + done) по finished_at
        err_rows = session.execute(
            select(
                models.SystemTask.task_type,
                models.SystemTask.state,
                func.count(models.SystemTask.id),
            )
            .where(
                models.SystemTask.state.in_(("done", "failed")),
                models.SystemTask.finished_at.is_not(None),
                models.SystemTask.finished_at
                >= func.now() - func.make_interval(0, 0, 0, 1),
            )
            .group_by(models.SystemTask.task_type, models.SystemTask.state)
        ).all()
        counts: dict[str, dict[str, int]] = {}
        for task_type, state, cnt in err_rows:
            counts.setdefault(task_type, {})[state] = cnt
        QUEUE_ERRORS.clear()
        for task_type, c in counts.items():
            total = c.get("done", 0) + c.get("failed", 0)
            if total > 0:
                QUEUE_ERRORS.labels(task_type=task_type).set(c.get("failed", 0) / total)
    finally:
        session.close()


def start_metrics_server() -> None:
    """HTTP-сервер :9808 + фоновое обновление метрик (поток-демон, 15 с)."""

    def _loop() -> None:
        while True:
            try:
                _update_metrics()
            except Exception as e:  # noqa: BLE001 — БД может быть недоступна
                log.warning("worker.metrics.update_failed", error=str(e))
            time.sleep(15)

    threading.Thread(target=_loop, daemon=True).start()
    start_http_server(9808)
