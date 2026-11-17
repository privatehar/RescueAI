"""SQLAlchemy engine management.

PostgreSQL is the durable source of truth. The engine is created lazily (importing this module
never opens a connection) and shared per process. API and worker processes each get their own
pool, which is why pool sizes are settings: total connections = processes x (pool + overflow).
"""

from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from rescueai.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,  # transparently replace connections dropped by a DB restart
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=5,  # fail fast instead of queueing forever when the pool is exhausted
        connect_args={
            "connect_timeout": 3,
            # Every session runs in UTC, so timestamps always come back as UTC.
            "options": "-c timezone=UTC",
        },
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    # expire_on_commit=False: objects stay readable after commit (no surprise lazy reloads
    # while building the HTTP response).
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def ping_database(timeout_seconds: float) -> None:
    """Raise if PostgreSQL cannot answer a trivial query within ``timeout_seconds``."""
    timeout_ms = max(1, int(timeout_seconds * 1000))
    with get_engine().connect() as connection:
        # set_config(..., true) is transaction-local, so the pooled connection is not affected.
        connection.execute(
            text("SELECT set_config('statement_timeout', :ms, true)"), {"ms": str(timeout_ms)}
        )
        connection.execute(text("SELECT 1"))


def dispose_engine() -> None:
    get_sessionmaker.cache_clear()
    if get_engine.cache_info().currsize:
        get_engine().dispose()
        get_engine.cache_clear()
