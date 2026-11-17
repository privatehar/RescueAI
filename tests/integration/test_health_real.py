"""Runs against REAL PostgreSQL and Redis (no fakes). Excluded from the default run.

    DATABASE_URL=... REDIS_URL=... uv run pytest -m integration

These prove that the connection settings, drivers, timeouts and health probes actually work
against real servers, which mocked tests cannot show.
"""

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from rescueai.core.config import get_settings
from rescueai.core.redis import close_redis
from rescueai.db.session import dispose_engine
from rescueai.main import create_app

pytestmark = pytest.mark.integration

HEALTH = "/api/v1/health"


@pytest.fixture
def real_client() -> Iterator[TestClient]:
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    dispose_engine()
    close_redis()
    get_settings.cache_clear()


def test_health_ok_with_real_services(real_client: TestClient) -> None:
    response = real_client.get(HEALTH)
    assert response.status_code == 200, response.text
    checks = response.json()["checks"]
    assert checks["database"]["status"] == "ok"
    assert checks["redis"]["status"] == "ok"


def test_unreachable_redis_gives_503_quickly(
    monkeypatch: pytest.MonkeyPatch, real_client: TestClient
) -> None:
    close_redis()
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # nothing listens on port 1
    get_settings.cache_clear()

    started = time.perf_counter()
    response = real_client.get(HEALTH)
    elapsed = time.perf_counter() - started

    assert response.status_code == 503
    assert response.json()["checks"]["redis"]["status"] == "error"
    assert response.json()["checks"]["database"]["status"] == "ok"
    assert elapsed < 5, "health endpoint must not hang on a dead dependency"


def test_unreachable_database_gives_503_quickly(
    monkeypatch: pytest.MonkeyPatch, real_client: TestClient
) -> None:
    dispose_engine()
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/none")
    get_settings.cache_clear()

    started = time.perf_counter()
    response = real_client.get(HEALTH)
    elapsed = time.perf_counter() - started

    assert response.status_code == 503
    assert response.json()["checks"]["database"]["status"] == "error"
    assert response.json()["checks"]["redis"]["status"] == "ok"
    assert elapsed < 8
