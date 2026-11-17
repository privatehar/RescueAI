"""Redis client management.

Redis is the Celery broker and holds only short-lived coordination data. It is never the
only copy of job state: PostgreSQL is. Losing Redis must not lose jobs.
"""

from functools import lru_cache

from redis import Redis

from rescueai.core.config import get_settings


@lru_cache
def get_redis_client() -> Redis:
    settings = get_settings()
    timeout = settings.health_check_timeout_seconds
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
        health_check_interval=30,
    )


def ping_redis() -> None:
    """Raise if Redis does not answer PING."""
    if not get_redis_client().ping():
        raise ConnectionError("Redis PING returned a falsy response")


def close_redis() -> None:
    if get_redis_client.cache_info().currsize:
        get_redis_client().close()
        get_redis_client.cache_clear()
