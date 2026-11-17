"""Shared fixtures.

Environment defaults are set *before* any rescueai import so Settings validates. Real env vars
(e.g. in CI or an integration run) take precedence thanks to ``setdefault``.
"""

import io
import json
import logging
import os
from collections.abc import Iterator

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# Unit tests must not need real services; startup behaviour is tested explicitly instead.
os.environ.setdefault("STARTUP_CHECK_ENABLED", "false")

import pytest
import structlog
from fastapi.testclient import TestClient

from rescueai.api.deps import get_database_probe, get_redis_probe
from rescueai.core.logging import configure_logging
from rescueai.main import create_app


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    yield
    # Tests that configure logging point the handler at a captured stream; undo that so it
    # cannot leak into later tests.
    logging.getLogger().handlers = []
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


@pytest.fixture
def log_stream() -> io.StringIO:
    return io.StringIO()


def read_log_records(stream: io.StringIO) -> list[dict[str, object]]:
    """Parse the JSON log lines written so far."""
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


@pytest.fixture
def client(log_stream: io.StringIO) -> Iterator[TestClient]:
    """App with healthy fake probes and JSON logs captured into ``log_stream``."""
    app = create_app()
    # create_app() configured logging to stdout; redirect to our buffer for assertions.
    configure_logging(level="INFO", json_logs=True, stream=log_stream)
    app.dependency_overrides[get_database_probe] = lambda: lambda: None
    app.dependency_overrides[get_redis_probe] = lambda: lambda: None
    with TestClient(app) as test_client:
        yield test_client
