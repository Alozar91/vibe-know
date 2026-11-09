# Кэш прав с инвалидацией NOTIFY/LISTEN (LLD §3.3, [уточнение LLD]).
#
# Состав кэша (по процессу api): снапшоты (object → entries), роли
# пользователя, флаг суперпользователя — данные, из которых собирается
# предикат §3.2. Инвалидация: после commit мутаций прав/ролей/групп —
# NOTIFY rights_invalidate; все процессы сбрасывают кэш. TTL 60 с —
# подстраховка. Кэш применяется ТОЛЬКО для чтения списков/поиска
# (§3.3); мутации и переходы всегда идут мимо кэша.
#
# Пороки ранних реализаций, которых здесь нет:
#   - инвалидация в памяти одного воркера не покрывает остальные —
#     поэтому NOTIFY/LISTEN, а не потокобезопасный dict сам по себе;
#   - LISTEN-соединение — отдельное (dedicated) соединение вне пула.
import threading
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.logging import get_logger

log = get_logger(__name__)

TTL_SECONDS = 60  # §3.3: подстраховка при потере NOTIFY
CHANNEL = "rights_invalidate"

_lock = threading.Lock()
_store: dict[str, tuple[float, object]] = {}  # key → (expires_at, value)
_generation = 0  # счётчик сбросов (LISTEN-поток инкрементирует)


def _now() -> float:
    return time.monotonic()


def get_cached(key: str):
    """Значение из кэша или None (истёк/сброшен)."""
    global _generation
    with _lock:
        entry = _store.get(key)
        if entry is None:
            return None
        expires_at, value, gen = entry
        if gen != _generation or expires_at < _now():
            _store.pop(key, None)
            return None
        return value


def put_cached(key: str, value) -> None:
    with _lock:
        _store[key] = (TTL_SECONDS + _now(), value, _generation)


def invalidate_local(reason: str = "manual") -> None:
    """Сброс локального кэша (вызывается и LISTEN-потоком, и после мутаций)."""
    global _generation
    with _lock:
        _store.clear()
        _generation += 1
    log.info({"event": "rights_cache.invalidate", "reason": reason})


def notify_invalidate(db: Session) -> None:
    """NOTIFY в ТЕКУЩЕЙ транзакции мутации: доставляется после её commit
    (PostgreSQL не доставляет NOTIFY до конца транзакции уведомителя)."""
    try:
        db.execute(text(f"NOTIFY {CHANNEL}"))
    except Exception:  # noqa: BLE001 — кэш не должен ломать мутацию
        log.warning({"event": "rights_cache.notify_failed"})


def commit_rights(db: Session) -> None:
    """commit мутации прав/ролей/групп с инвалидацией (§3.3).

    NOTIFY ставится в транзакции (доставка — сразу после commit); локальный
    кэш сбрасывается немедленно, не дожидаясь доставки в свой listener.
    """
    notify_invalidate(db)
    db.commit()
    invalidate_local("mutation")


def start_listener() -> None:
    """LISTEN в фоновом потоке на выделенном соединении (вне пула).

    SQLite (тесты) не поддерживает NOTIFY — поток не стартует (кэш
    деградирует до TTL-инвалидации, что корректно для одного процесса).
    """
    from app.config import get_settings

    if get_settings().database_url.startswith("sqlite"):
        log.info({"event": "rights_cache.listener_skipped", "reason": "sqlite"})
        return

    def _listen() -> None:
        # psycopg3: выделенное соединение вне пула, autocommit; notify читает
        # conn.notifies (внутренний поток psycopg3 заполняет очередь)
        import psycopg

        conninfo = get_settings().database_url
        if "+psycopg" in conninfo:  # sqlalchemy-URL → libpq conninfo
            conninfo = conninfo.replace("postgresql+psycopg://", "postgresql://", 1)
        while True:
            try:
                conn = psycopg.connect(conninfo, autocommit=True)
                conn.execute(f"LISTEN {CHANNEL}")
                log.info({"event": "rights_cache.listening", "channel": CHANNEL})
                for notify in conn.notifies():  # блокирующий генератор
                    if notify.channel == CHANNEL:
                        invalidate_local("notify")
            except Exception as e:  # noqa: BLE001 — разрыв: переподключение
                log.warning({"event": "rights_cache.listen_error", "error": str(e)[:200]})
                time.sleep(5)

    t = threading.Thread(target=_listen, name="rights-cache-listener", daemon=True)
    t.start()
