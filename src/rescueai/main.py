"""Application factory.

Run with:  uvicorn rescueai.main:create_app --factory
There is deliberately no module-level ``app``: importing this module has no side effects
(no logging setup, no settings validation, no connections).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rescueai import __version__
from rescueai.api.deps import get_database_probe, get_redis_probe
from rescueai.api.errors import register_error_handlers
from rescueai.api.v1.router import api_router
from rescueai.core.config import get_settings
from rescueai.core.correlation import CorrelationIdMiddleware
from rescueai.core.logging import configure_logging, get_logger
from rescueai.core.redis import close_redis
from rescueai.core.startup import wait_for_dependencies
from rescueai.db.session import dispose_engine


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.use_json_logs)
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if settings.startup_check_enabled:
            # Raises StartupError (-> process exits non-zero) if PostgreSQL/Redis never become
            # reachable within the budget. Runs in a thread: the probes are blocking calls.
            await asyncio.to_thread(
                wait_for_dependencies,
                {"database": get_database_probe(), "redis": get_redis_probe()},
                max_wait_seconds=settings.startup_max_wait_seconds,
            )
        logger.info("app_started", version=__version__, environment=settings.environment)
        yield
        dispose_engine()
        close_redis()
        logger.info("app_stopped")

    app = FastAPI(title="RescueAI", version=__version__, lifespan=lifespan)
    app.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    return app
