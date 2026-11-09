# Единая точка конфигурации логирования: структурированные логи в stdout (HLD §8.3).
# ПДн и содержимое материалов в логи не попадают (FR-142, HLD §8.3).
import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Настраивает structlog + stdlib: JSON-строки в stdout."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level.upper(),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)
