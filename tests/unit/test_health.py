from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from rescueai.api.deps import HealthProbe, get_database_probe, get_redis_probe

HEALTH = "/api/v1/health"


def _failing(exc: Exception) -> HealthProbe:
    def probe() -> None:
        raise exc

    return probe


def _override(
    client: TestClient, dependency: Callable[[], HealthProbe], probe: HealthProbe
) -> None:
    client.app.dependency_overrides[dependency] = lambda: probe  # type: ignore[attr-defined]


def test_all_dependencies_healthy_returns_200(client: TestClient) -> None:
    response = client.get(HEALTH)
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"api", "database", "redis"}
    assert all(check["status"] == "ok" for check in body["checks"].values())
    assert body["checks"]["database"]["latency_ms"] >= 0
    assert body["version"]


def test_database_down_returns_503_and_degraded(client: TestClient) -> None:
    _override(client, get_database_probe, _failing(ConnectionError("boom")))
    response = client.get(HEALTH)
    body = response.json()

    assert response.status_code == 503
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == {"status": "error", "error_type": "ConnectionError"}
    assert body["checks"]["redis"]["status"] == "ok"  # failure isolated to one dependency
    assert body["checks"]["api"]["status"] == "ok"


def test_redis_down_returns_503_and_degraded(client: TestClient) -> None:
    _override(client, get_redis_probe, _failing(TimeoutError("slow")))
    response = client.get(HEALTH)
    body = response.json()

    assert response.status_code == 503
    assert body["checks"]["redis"]["error_type"] == "TimeoutError"
    assert body["checks"]["database"]["status"] == "ok"


def test_both_down_reports_both(client: TestClient) -> None:
    _override(client, get_database_probe, _failing(RuntimeError("x")))
    _override(client, get_redis_probe, _failing(RuntimeError("y")))
    body = client.get(HEALTH).json()
    assert body["checks"]["database"]["status"] == "error"
    assert body["checks"]["redis"]["status"] == "error"


@pytest.mark.parametrize("message", ["password=hunter2 host=db.internal", "redis://:pw@10.0.0.5"])
def test_error_messages_never_leak_into_response(client: TestClient, message: str) -> None:
    _override(client, get_database_probe, _failing(RuntimeError(message)))
    response = client.get(HEALTH)
    assert message not in response.text
    assert "hunter2" not in response.text


def test_unknown_route_is_404(client: TestClient) -> None:
    assert client.get("/health").status_code == 404  # only /api/v1/health exists
