import io

import pytest
from fastapi.testclient import TestClient

from rescueai.core.correlation import CORRELATION_HEADER, resolve_correlation_id
from rescueai.core.logging import configure_logging
from rescueai.main import create_app
from tests.conftest import read_log_records

HEALTH = "/api/v1/health"


def test_generates_correlation_id_when_absent(client: TestClient) -> None:
    response = client.get(HEALTH)
    generated = response.headers[CORRELATION_HEADER]
    assert len(generated) == 32  # uuid4 hex


def test_each_request_gets_a_distinct_generated_id(client: TestClient) -> None:
    first = client.get(HEALTH).headers[CORRELATION_HEADER]
    second = client.get(HEALTH).headers[CORRELATION_HEADER]
    assert first != second


def test_echoes_valid_incoming_id(client: TestClient) -> None:
    response = client.get(HEALTH, headers={CORRELATION_HEADER: "trace-123.abc_DEF"})
    assert response.headers[CORRELATION_HEADER] == "trace-123.abc_DEF"


@pytest.mark.parametrize("bad", ["has space", "semi;colon", "a" * 65, "<script>", "emoji-\u2603"])
def test_unsafe_incoming_id_is_replaced_not_echoed(client: TestClient, bad: str) -> None:
    # httpx only lets us send latin-1 safe values; "\u2603" is encoded as UTF-8 bytes.
    raw_headers = [(CORRELATION_HEADER.encode(), bad.encode("utf-8"))]
    response = client.get(HEALTH, headers=raw_headers)
    returned = response.headers[CORRELATION_HEADER]
    assert returned != bad
    assert len(returned) == 32


def test_access_log_carries_correlation_id_and_omits_query_string(
    client: TestClient, log_stream: io.StringIO
) -> None:
    client.get(HEALTH + "?token=SUPERSECRET", headers={CORRELATION_HEADER: "req-42"})

    assert "SUPERSECRET" not in log_stream.getvalue()
    access = next(r for r in read_log_records(log_stream) if r["event"] == "request_completed")
    assert access["correlation_id"] == "req-42"
    assert access["path"] == HEALTH
    assert access["method"] == "GET"
    assert access["status_code"] == 200
    assert isinstance(access["duration_ms"], float)
    assert access["duration_ms"] >= 0


def test_correlation_context_does_not_leak_between_requests(
    client: TestClient, log_stream: io.StringIO
) -> None:
    client.get(HEALTH, headers={CORRELATION_HEADER: "first-req"})
    client.get(HEALTH, headers={CORRELATION_HEADER: "second-req"})
    ids = [
        r["correlation_id"]
        for r in read_log_records(log_stream)
        if r["event"] == "request_completed"
    ]
    assert ids == ["first-req", "second-req"]


def test_app_lifecycle_logs_do_not_carry_a_stale_correlation_id(log_stream: io.StringIO) -> None:
    """Startup/shutdown logs happen outside any request, so must have no correlation_id."""
    app = create_app()
    configure_logging(level="INFO", json_logs=True, stream=log_stream)
    with TestClient(app):
        pass
    lifecycle = [
        r for r in read_log_records(log_stream) if r["event"] in {"app_started", "app_stopped"}
    ]
    assert [r["event"] for r in lifecycle] == ["app_started", "app_stopped"]
    assert all("correlation_id" not in r for r in lifecycle)


def test_resolve_none_and_empty_generate_ids() -> None:
    assert len(resolve_correlation_id(None)) == 32
    assert len(resolve_correlation_id("")) == 32
