# SQLAlchemy 2: движок и фабрика сессий (HLD §4).
# Единственная БД — kb; БД keycloak — тот же экземпляр Postgres, отдельная база (HLD §3.2).
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine = None
_session_factory = None


def get_engine():
    """Ленивый движок (создаётся при первом обращении; pool_pre_ping — устойчивость к рестартам PG)."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
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
