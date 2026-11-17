import io

import pytest
from fastapi.testclient import TestClient

from rescueai.api.deps import get_database_probe, get_redis_probe
from rescueai.core.config import get_settings
from rescueai.core.logging import configure_logging
from rescueai.core.startup import StartupError, wait_for_dependencies
from rescueai.main import create_app
from tests.conftest import read_log_records


class FakeClock:
    """Deterministic time: ``sleep`` advances ``now``; nothing really waits."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def flaky(failures: int, exc: Exception) -> tuple[list[int], object]:
    calls = [0]

    def probe() -> None:
        calls[0] += 1
        if calls[0] <= failures:
            raise exc

    return calls, probe


def test_returns_immediately_when_all_ready() -> None:
    clock = FakeClock()
    wait_for_dependencies(
        {"database": lambda: None, "redis": lambda: None},
        max_wait_seconds=30,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert clock.sleeps == []


def test_retries_until_dependency_becomes_ready() -> None:
    clock = FakeClock()
    calls, probe = flaky(3, ConnectionError("not yet"))
    wait_for_dependencies(
        {"database": probe},  # type: ignore[dict-item]
        max_wait_seconds=30,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert calls[0] == 4  # three failures, then success
    assert len(clock.sleeps) == 3


def test_backoff_doubles_and_is_capped() -> None:
    clock = FakeClock()
    _, probe = flaky(6, ConnectionError("x"))
    wait_for_dependencies(
        {"database": probe},  # type: ignore[dict-item]
        max_wait_seconds=1000,
        initial_delay_seconds=0.5,
        max_delay_seconds=4.0,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert clock.sleeps == [0.5, 1.0, 2.0, 4.0, 4.0, 4.0]


def test_healthy_dependency_is_not_reprobed_while_waiting_for_another() -> None:
    clock = FakeClock()
    redis_calls, redis_probe = flaky(0, ConnectionError("x"))
    _, db_probe = flaky(2, ConnectionError("x"))
    wait_for_dependencies(
        {"redis": redis_probe, "database": db_probe},  # type: ignore[dict-item]
        max_wait_seconds=30,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert redis_calls[0] == 1


def test_raises_clear_error_naming_failed_dependencies_when_budget_spent() -> None:
    clock = FakeClock()

    def down() -> None:
        raise ConnectionError("password=hunter2 refused")

    with pytest.raises(StartupError) as excinfo:
        wait_for_dependencies(
            {"database": down, "redis": lambda: None},
            max_wait_seconds=5,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
    message = str(excinfo.value)
    assert "database (ConnectionError)" in message
    assert "redis" not in message.split("not ready")[1].split(".")[0]  # redis was healthy
    assert "hunter2" not in message  # exception text must not leak into the error
    assert clock.now <= 5  # never sleeps past the deadline


def test_zero_budget_still_probes_once_then_fails() -> None:
    calls, probe = flaky(99, ConnectionError("x"))
    with pytest.raises(StartupError):
        wait_for_dependencies({"database": probe}, max_wait_seconds=0)  # type: ignore[dict-item]
    assert calls[0] == 1


def test_app_startup_fails_fast_when_dependencies_unreachable(
    monkeypatch: pytest.MonkeyPatch, log_stream: io.StringIO
) -> None:
    monkeypatch.setenv("STARTUP_CHECK_ENABLED", "true")
    monkeypatch.setenv("STARTUP_MAX_WAIT_SECONDS", "0")
    get_settings.cache_clear()
    try:
        app = create_app()
        configure_logging(level="INFO", json_logs=True, stream=log_stream)

        def broken() -> None:
            raise ConnectionError("down")

        app.dependency_overrides[get_database_probe] = lambda: broken
        app.dependency_overrides[get_redis_probe] = lambda: broken
        # create_app() calls the provider functions directly (not via DI), so patch there too.
        monkeypatch.setattr("rescueai.main.get_database_probe", lambda: broken)
        monkeypatch.setattr("rescueai.main.get_redis_probe", lambda: broken)

        with (
            pytest.raises(
                StartupError, match=r"database \(ConnectionError\), redis \(ConnectionError\)"
            ),
            TestClient(app),
        ):
            pass
        events = [r["event"] for r in read_log_records(log_stream)]
        assert "app_started" not in events  # never reported as started
        assert events.count("dependency_unavailable") == 2
    finally:
        get_settings.cache_clear()


def test_app_startup_proceeds_when_dependencies_ready(
    monkeypatch: pytest.MonkeyPatch, log_stream: io.StringIO
) -> None:
    monkeypatch.setenv("STARTUP_CHECK_ENABLED", "true")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr("rescueai.main.get_database_probe", lambda: lambda: None)
        monkeypatch.setattr("rescueai.main.get_redis_probe", lambda: lambda: None)
        app = create_app()
        configure_logging(level="INFO", json_logs=True, stream=log_stream)
        with TestClient(app):
            pass
        events = [r["event"] for r in read_log_records(log_stream)]
        assert events.count("dependency_ready") == 2
        assert "app_started" in events
    finally:
        get_settings.cache_clear()
