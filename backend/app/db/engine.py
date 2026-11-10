# SQLAlchemy 2: движок и фабрика сессий (HLD §4).
# Единственная БД — kb; БД keycloak — тот же экземпляр Postgres, отдельная база (HLD §3.2).
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine = None
_session_factory = None


def get_engine():
    """Ленивый движок (создаётся при первом обращении; pool_pre_ping — устойчивость к рестартам PG).

    Пул: 25 + 15 = 40 на воркер (этап 11, NFR-008) — sync-эндпоинты исполняются в
    threadpool FastAPI (лимит anyio 40 потоков/воркер); пул = потолку потоков,
    иначе очередь пула давала таймауты 500 под пиками. 4 воркера × 40 = 160 макс
    + worker ~15 + LISTEN 4 + JDBC Keycloak + экспортеры ≈ 190 < 250 (compose).
    """
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url, pool_pre_ping=True,
            pool_size=25, max_overflow=15, pool_timeout=30,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: сессия на запрос; rollback при ошибке (частичное состояние не живёт)."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
