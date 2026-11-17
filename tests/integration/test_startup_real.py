"""Startup behaviour against REAL PostgreSQL and Redis (run with: pytest -m integration)."""

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from rescueai.core.config import get_settings
from rescueai.core.redis import close_redis
from rescueai.core.startup import StartupError
from rescueai.db.session import dispose_engine
from rescueai.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("STARTUP_CHECK_ENABLED", "true")
    get_settings.cache_clear()
    yield
    dispose_engine()
    close_redis()
    get_settings.cache_clear()


def test_app_starts_and_serves_when_infrastructure_is_up() -> None:
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/health").status_code == 200


def test_startup_fails_fast_with_clear_error_when_redis_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # nothing listens on port 1
    monkeypatch.setenv("STARTUP_MAX_WAIT_SECONDS", "2")
    get_settings.cache_clear()

    started = time.perf_counter()
    with pytest.raises(StartupError, match=r"redis \(ConnectionError\)"), TestClient(create_app()):
        pass
    elapsed = time.perf_counter() - started

    assert 1.5 <= elapsed < 8, f"should retry for about the budget, took {elapsed:.1f}s"


def test_startup_fails_fast_when_database_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/none")
    monkeypatch.setenv("STARTUP_MAX_WAIT_SECONDS", "2")
    get_settings.cache_clear()

    with (
        pytest.raises(StartupError, match=r"database \(OperationalError\)"),
        TestClient(create_app()),
    ):
        pass
