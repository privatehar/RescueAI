"""FastAPI dependencies. Providers are overridable in tests via ``app.dependency_overrides``."""

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from rescueai.core.config import get_settings
from rescueai.core.redis import ping_redis
from rescueai.db.session import get_sessionmaker, ping_database

HealthProbe = Callable[[], None]


def get_database_probe() -> HealthProbe:
    timeout = get_settings().health_check_timeout_seconds
    return lambda: ping_database(timeout)


def get_redis_probe() -> HealthProbe:
    return ping_redis


def get_session() -> Iterator[Session]:
    """One database session per request. ``close()`` rolls back anything not committed, so an
    endpoint can never leak an open transaction or a half-finished write."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


# Annotated aliases: the modern FastAPI idiom for declaring a dependency in a signature.
DatabaseProbe = Annotated[HealthProbe, Depends(get_database_probe)]
RedisProbe = Annotated[HealthProbe, Depends(get_redis_probe)]
SessionDep = Annotated[Session, Depends(get_session)]
