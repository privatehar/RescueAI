"""End-to-end: HTTP -> FastAPI -> service -> PostgreSQL (real), no stubs."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from rescueai.core.config import get_settings
from rescueai.db.session import dispose_engine
from rescueai.main import create_app
from tests.integration.helpers import count, insert_attempt, insert_job

pytestmark = pytest.mark.integration

JOBS = "/api/v1/jobs"
ETL = {"job_type": "etl", "payload": {"source_dataset": "orders", "target_table": "dw_orders"}}
REPORT = {"job_type": "report", "payload": {"report_type": "daily_summary"}}
API_CALL = {"job_type": "api_call", "payload": {"url": "https://api.example.com/v1/ping"}}

DETAIL_FIELDS = {
    "id", "job_type", "status", "attempt_count", "max_attempts", "created_at", "updated_at",
    "started_at", "completed_at", "duration_ms", "payload", "idempotency_key", "next_retry_at",
    "cancel_requested", "correlation_id",
}  # fmt: skip
SUMMARY_FIELDS = DETAIL_FIELDS - {
    "payload",
    "idempotency_key",
    "next_retry_at",
    "cancel_requested",
    "correlation_id",
}
ATTEMPT_FIELDS = {
    "id", "attempt_number", "status", "error_type", "error_message", "retryable", "started_at",
    "finished_at", "duration_ms",
}  # fmt: skip


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def set_state(session: Session, job_id: str, status: str) -> None:
    """Move a job into ``status`` directly in SQL (the execution engine does not exist yet)."""
    extra = (
        ", completed_at = now()"
        if status in {"SUCCEEDED", "FAILED", "DEAD_LETTER", "CANCELLED"}
        else ""
    )
    session.execute(
        text(f"UPDATE jobs SET status = :s{extra} WHERE id = :i"), {"s": status, "i": job_id}
    )
    session.commit()


# ------------------------------------------------------------------ create
def test_create_then_get_roundtrip(api_client: TestClient, session: Session) -> None:
    created = api_client.post(JOBS, json={**ETL, "idempotency_key": "order-1"})
    body = created.json()

    assert created.status_code == 202
    assert created.headers["location"] == f"{JOBS}/{body['id']}"
    assert set(body) == DETAIL_FIELDS
    assert body["status"] == "PENDING"
    assert body["attempt_count"] == 0
    assert body["max_attempts"] == 5
    assert body["payload"] == {
        "source_dataset": "orders",
        "target_table": "dw_orders",
        "batch_size": 500,
    }
    assert body["started_at"] is None
    assert body["duration_ms"] is None

    fetched = api_client.get(f"{JOBS}/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body
    assert count(session, "jobs") == 1


def test_timestamps_are_utc(api_client: TestClient) -> None:
    body = api_client.post(JOBS, json=ETL).json()
    assert body["created_at"].endswith("Z")
    created = parse_utc(body["created_at"])
    assert created.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - created) < timedelta(minutes=1)


def test_each_job_type_can_be_created(api_client: TestClient) -> None:
    for request in (ETL, REPORT, API_CALL):
        response = api_client.post(JOBS, json=request)
        assert response.status_code == 202
        assert response.json()["job_type"] == request["job_type"]


@pytest.mark.parametrize(
    "body",
    [
        {
            "job_type": "etl",
            "payload": {"source_dataset": "o", "target_table": "t", "batch_size": "500"},
        },
        {"job_type": "etl", "payload": {"source_dataset": "Has Spaces", "target_table": "t"}},
        {"job_type": "api_call", "payload": {"url": "file:///etc/passwd"}},
        {"job_type": "api_call", "payload": {"url": "https://user:pw@example.com"}},
        {"job_type": "shell", "payload": {"cmd": "rm -rf /"}},
        {"job_type": "etl"},
        {**ETL, "idempotency_key": "bad key!"},
        {**ETL, "max_attempts": 99},
    ],
)
def test_invalid_requests_are_rejected_and_persist_nothing(
    api_client: TestClient, session: Session, body: dict[str, Any]
) -> None:
    response = api_client.post(JOBS, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert (
        count(session, "jobs"),
        count(session, "outbox_events"),
        count(session, "audit_events"),
    ) == (0, 0, 0)


def test_correlation_id_is_persisted_on_job_and_audit_event(
    api_client: TestClient, session: Session
) -> None:
    body = api_client.post(JOBS, json=ETL, headers={"X-Correlation-ID": "trace-abc-123"}).json()
    assert body["correlation_id"] == "trace-abc-123"
    assert api_client.get(f"{JOBS}/{body['id']}").json()["correlation_id"] == "trace-abc-123"
    audit_cid = session.execute(text("SELECT correlation_id FROM audit_events")).scalar_one()
    assert audit_cid == "trace-abc-123"


# ------------------------------------------------------------ idempotency
def test_duplicate_idempotency_key_returns_the_original_job(
    api_client: TestClient, session: Session
) -> None:
    first = api_client.post(JOBS, json={**ETL, "idempotency_key": "dup-1"})
    second = api_client.post(JOBS, json={**ETL, "idempotency_key": "dup-1"})

    assert (first.status_code, second.status_code) == (202, 200)
    assert second.headers["idempotent-replayed"] == "true"
    assert "location" not in second.headers
    assert second.json()["id"] == first.json()["id"]
    assert count(session, "jobs") == 1


def test_reusing_a_key_for_a_different_request_is_409(
    api_client: TestClient, session: Session
) -> None:
    api_client.post(JOBS, json={**ETL, "idempotency_key": "dup-2"})
    response = api_client.post(JOBS, json={**REPORT, "idempotency_key": "dup-2"})

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "idempotency_conflict"
    # The error must not echo either request's payload.
    assert "orders" not in response.text
    assert "daily_summary" not in response.text
    assert count(session, "jobs") == 1


def test_concurrent_http_requests_with_the_same_key_create_one_job(
    api_client: TestClient, session: Session
) -> None:
    def post(_: int) -> Any:
        return api_client.post(JOBS, json={**ETL, "idempotency_key": "race-http"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(post, range(8)))

    assert sorted(r.status_code for r in responses) == [200] * 7 + [202]
    assert len({r.json()["id"] for r in responses}) == 1
    assert count(session, "jobs") == 1


# ------------------------------------------------------------------- read
def test_get_unknown_job_is_404(api_client: TestClient) -> None:
    response = api_client.get(f"{JOBS}/00000000-0000-4000-8000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_get_malformed_id_is_422(api_client: TestClient) -> None:
    assert api_client.get(f"{JOBS}/123").status_code == 422


def test_list_uses_summaries_without_payload(api_client: TestClient) -> None:
    api_client.post(JOBS, json=ETL)
    body = api_client.get(JOBS).json()
    assert body["total"] == 1
    assert set(body["items"][0]) == SUMMARY_FIELDS


def test_list_pagination_walks_every_job_exactly_once(api_client: TestClient) -> None:
    created = [api_client.post(JOBS, json=ETL).json()["id"] for _ in range(7)]

    pages = [api_client.get(JOBS, params={"limit": 3, "offset": o}).json() for o in (0, 3, 6)]
    assert [len(p["items"]) for p in pages] == [3, 3, 1]
    assert {p["total"] for p in pages} == {7}
    seen = [item["id"] for p in pages for item in p["items"]]
    assert seen == list(reversed(created))  # newest first, no gaps, no repeats


def test_list_filters_over_http(api_client: TestClient, session: Session) -> None:
    etl = [api_client.post(JOBS, json=ETL).json()["id"] for _ in range(3)]
    report = [api_client.post(JOBS, json=REPORT).json()["id"] for _ in range(2)]
    set_state(session, etl[0], "FAILED")
    set_state(session, report[0], "FAILED")
    set_state(session, report[1], "QUEUED")

    by_type = api_client.get(JOBS, params={"job_type": "report"}).json()
    assert {i["id"] for i in by_type["items"]} == set(report)

    by_status = api_client.get(JOBS, params={"status": "FAILED"}).json()
    assert {i["id"] for i in by_status["items"]} == {etl[0], report[0]}
    assert by_status["total"] == 2

    both = api_client.get(JOBS, params={"status": "FAILED", "job_type": "etl"}).json()
    assert [i["id"] for i in both["items"]] == [etl[0]]

    none = api_client.get(JOBS, params={"status": "DEAD_LETTER"}).json()
    assert (none["items"], none["total"]) == ([], 0)


def test_list_created_range_filter_over_http(api_client: TestClient) -> None:
    api_client.post(JOBS, json=ETL)
    now = datetime.now(UTC)
    future = (now + timedelta(days=1)).isoformat()
    past = (now - timedelta(days=1)).isoformat()

    assert api_client.get(JOBS, params={"created_after": future}).json()["total"] == 0
    assert api_client.get(JOBS, params={"created_before": past}).json()["total"] == 0
    assert (
        api_client.get(JOBS, params={"created_after": past, "created_before": future}).json()[
            "total"
        ]
        == 1
    )


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "offset=-5", "status=nope", "created_after=2026-01-01"]
)
def test_bad_list_queries_are_422_even_with_real_database(
    api_client: TestClient, query: str
) -> None:
    assert api_client.get(f"{JOBS}?{query}").status_code == 422


def test_sql_injection_attempts_are_inert(api_client: TestClient, session: Session) -> None:
    api_client.post(JOBS, json=ETL)
    attack = "etl'; DROP TABLE jobs; --"
    assert api_client.get(JOBS, params={"job_type": attack}).status_code == 422
    assert api_client.post(JOBS, json={**ETL, "idempotency_key": attack}).status_code == 422
    assert count(session, "jobs") == 1  # table intact


# --------------------------------------------------------------- attempts
def test_attempt_history_is_ordered_and_hides_internals(
    api_client: TestClient, session: Session
) -> None:
    job_id = api_client.post(JOBS, json=ETL).json()["id"]
    insert_attempt(
        session, job_id, attempt_number=2, status="SUCCEEDED", started_at=datetime.now(UTC)
    )
    insert_attempt(
        session, job_id, attempt_number=1, status="FAILED", error_type="ConnectionTimeout",
        error_message="upstream timed out", retryable=True,
        stack_trace="Traceback (most recent call last): File '/srv/app/secret_path.py'",
        worker_id="worker-host-9",
    )  # fmt: skip
    session.commit()

    response = api_client.get(f"{JOBS}/{job_id}/attempts")
    body = response.json()

    assert response.status_code == 200
    assert body["job_id"] == job_id
    assert [a["attempt_number"] for a in body["items"]] == [1, 2]
    assert all(set(a) == ATTEMPT_FIELDS for a in body["items"])
    assert body["items"][0]["error_type"] == "ConnectionTimeout"
    assert body["items"][0]["retryable"] is True
    for leaked in ("secret_path", "Traceback", "worker-host-9", "stack_trace", "worker_id"):
        assert leaked not in response.text


def test_new_job_has_an_empty_attempt_history(api_client: TestClient) -> None:
    job_id = api_client.post(JOBS, json=ETL).json()["id"]
    assert api_client.get(f"{JOBS}/{job_id}/attempts").json() == {"job_id": job_id, "items": []}


def test_attempts_of_unknown_job_is_404(api_client: TestClient) -> None:
    response = api_client.get(f"{JOBS}/00000000-0000-4000-8000-000000000000/attempts")
    assert response.status_code == 404


def test_internal_columns_never_appear_in_any_response(
    api_client: TestClient, session: Session
) -> None:
    job_id = insert_job(
        session, locked_by="worker-secret-42", status="RUNNING", started_at=datetime.now(UTC)
    )
    session.commit()
    texts = [
        api_client.get(f"{JOBS}/{job_id}").text,
        api_client.get(JOBS).text,
        api_client.post(JOBS, json=ETL).text,
    ]
    for text_ in texts:
        for internal in (
            "worker-secret-42",
            "request_hash",
            "locked_by",
            "heartbeat_at",
            "version",
        ):
            assert internal not in text_


# --------------------------------------------------- persistence & failures
def test_jobs_survive_an_api_restart(app_db: str, session: Session) -> None:
    with TestClient(create_app()) as first_process:
        job_id = first_process.post(JOBS, json={**ETL, "idempotency_key": "persist-1"}).json()["id"]
    # leaving the `with` block runs the shutdown hook: the engine/pool is disposed.

    with TestClient(create_app()) as second_process:  # a brand-new app instance = a restart
        again = second_process.get(f"{JOBS}/{job_id}")
        assert again.status_code == 200
        assert again.json()["id"] == job_id
        assert second_process.get(JOBS).json()["total"] == 1
        # and idempotency still holds across the restart:
        replay = second_process.post(JOBS, json={**ETL, "idempotency_key": "persist-1"})
        assert (replay.status_code, replay.json()["id"]) == (200, job_id)
    assert count(session, "jobs") == 1


def test_database_outage_is_a_503_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/none"
    )  # nothing listens
    get_settings.cache_clear()
    dispose_engine()
    try:
        with TestClient(create_app(), raise_server_exceptions=False) as client:
            for response in (client.post(JOBS, json=ETL), client.get(JOBS)):
                assert response.status_code == 503
                assert response.json()["error"]["code"] == "service_unavailable"
                assert response.headers["retry-after"] == "5"
                assert "127.0.0.1" not in response.text  # no connection details leak out
            assert client.get("/api/v1/health").status_code == 503
    finally:
        dispose_engine()
        monkeypatch.undo()
        get_settings.cache_clear()
        assert os.environ["DATABASE_URL"]  # env restored for later tests
