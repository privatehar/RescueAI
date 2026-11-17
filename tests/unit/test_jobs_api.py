"""HTTP behaviour of the job endpoints, with the service layer stubbed (no database)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from rescueai.core.errors import IdempotencyConflictError, JobNotFoundError
from rescueai.db.enums import AttemptStatus, JobStatus, JobType
from rescueai.db.models import Job, JobAttempt
from rescueai.repositories.jobs import JobFilters
from rescueai.services import job_service
from rescueai.services.job_service import CreateJobResult

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
ETL_BODY = {
    "job_type": "etl",
    "payload": {"source_dataset": "orders", "target_table": "dw_orders"},
}

# Exactly what the API may expose. Anything else on the model must stay internal.
DETAIL_FIELDS = {
    "id", "job_type", "status", "attempt_count", "max_attempts", "created_at", "updated_at",
    "started_at", "completed_at", "duration_ms", "payload", "idempotency_key", "next_retry_at",
    "cancel_requested", "correlation_id",
}  # fmt: skip
SUMMARY_FIELDS = {
    "id", "job_type", "status", "attempt_count", "max_attempts", "created_at", "updated_at",
    "started_at", "completed_at", "duration_ms",
}  # fmt: skip
ATTEMPT_FIELDS = {
    "id", "attempt_number", "status", "error_type", "error_message", "retryable", "started_at",
    "finished_at", "duration_ms",
}  # fmt: skip
INTERNAL_VALUES = ("worker-secret-7", "a" * 64, "SECRET-TRACE", "host-internal-3")


def make_job(**overrides: Any) -> Job:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "job_type": JobType.ETL,
        "payload": {"source_dataset": "orders", "target_table": "dw_orders", "batch_size": 500},
        "request_hash": "a" * 64,  # internal
        "status": JobStatus.PENDING,
        "attempt_count": 0,
        "max_attempts": 5,
        "idempotency_key": None,
        "correlation_id": None,
        "next_retry_at": None,
        "locked_by": "worker-secret-7",  # internal
        "locked_at": NOW,  # internal
        "heartbeat_at": NOW,  # internal
        "cancel_requested": False,
        "version": 3,  # internal
        "created_at": NOW,
        "updated_at": NOW,
        "started_at": None,
        "completed_at": None,
    }
    values.update(overrides)
    return Job(**values)


def make_attempt(job_id: uuid.UUID, number: int = 1, **overrides: Any) -> JobAttempt:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "job_id": job_id,
        "attempt_number": number,
        "status": AttemptStatus.FAILED,
        "error_type": "ConnectionTimeout",
        "error_message": "upstream timed out",
        "stack_trace": "Traceback ... SECRET-TRACE ...",  # internal
        "retryable": True,
        "worker_id": "host-internal-3",  # internal
        "correlation_id": None,
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=2),
        "duration_ms": 2000,
    }
    values.update(overrides)
    return JobAttempt(**values)


def assert_no_internals(text: str) -> None:
    for internal in INTERNAL_VALUES:
        assert internal not in text, f"internal value leaked: {internal}"
    for name in (
        "request_hash",
        "locked_by",
        "locked_at",
        "heartbeat_at",
        "stack_trace",
        "worker_id",
        "version",
    ):
        assert name not in text, f"internal field leaked: {name}"


# ---------------------------------------------------------------- POST /jobs
def test_create_returns_202_location_and_only_public_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = make_job()
    monkeypatch.setattr(job_service, "create_job", lambda *a, **k: CreateJobResult(job, True))

    response = client.post("/api/v1/jobs", json=ETL_BODY)

    assert response.status_code == 202
    assert response.headers["location"] == f"/api/v1/jobs/{job.id}"
    assert "idempotent-replayed" not in response.headers
    assert set(response.json()) == DETAIL_FIELDS
    assert_no_internals(response.text)


def test_replay_returns_200_and_replay_header(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        job_service, "create_job", lambda *a, **k: CreateJobResult(make_job(), False)
    )
    response = client.post("/api/v1/jobs", json={**ETL_BODY, "idempotency_key": "k1"})
    assert response.status_code == 200
    assert response.headers["idempotent-replayed"] == "true"
    assert "location" not in response.headers


def test_idempotency_conflict_is_409(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def conflict(*_a: Any, **_k: Any) -> CreateJobResult:
        raise IdempotencyConflictError

    monkeypatch.setattr(job_service, "create_job", conflict)
    response = client.post("/api/v1/jobs", json={**ETL_BODY, "idempotency_key": "k1"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"


def test_create_passes_correlation_id_and_default_max_attempts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake(_session: Any, request: Any, **kwargs: Any) -> CreateJobResult:
        seen.update(kwargs, request=request)
        return CreateJobResult(make_job(), True)

    monkeypatch.setattr(job_service, "create_job", fake)
    client.post("/api/v1/jobs", json=ETL_BODY, headers={"X-Correlation-ID": "trace-77"})
    assert seen["correlation_id"] == "trace-77"
    assert seen["default_max_attempts"] == 5
    assert seen["request"].job_type == "etl"


@pytest.mark.parametrize(
    "body",
    [
        {"job_type": "etl"},
        {"job_type": "unknown", "payload": {}},
        {**ETL_BODY, "extra": 1},
        {
            "job_type": "etl",
            "payload": {"source_dataset": "o", "target_table": "t", "batch_size": "9"},
        },
    ],
)
def test_invalid_create_requests_never_reach_the_service(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]
) -> None:
    def must_not_run(*_a: Any, **_k: Any) -> None:
        raise AssertionError("service must not be called for an invalid request")

    monkeypatch.setattr(job_service, "create_job", must_not_run)
    response = client.post("/api/v1/jobs", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ------------------------------------------------------------ GET /jobs/{id}
def test_get_job_returns_public_fields_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = make_job(
        status=JobStatus.SUCCEEDED, started_at=NOW, completed_at=NOW + timedelta(seconds=3)
    )
    monkeypatch.setattr(job_service, "get_job", lambda _s, _id: job)
    response = client.get(f"/api/v1/jobs/{job.id}")
    body = response.json()
    assert response.status_code == 200
    assert set(body) == DETAIL_FIELDS
    assert body["duration_ms"] == 3000
    assert body["created_at"].endswith("Z")  # UTC
    assert_no_internals(response.text)


def test_get_unknown_job_is_404_envelope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(_s: Any, job_id: uuid.UUID) -> Job:
        raise JobNotFoundError(job_id)

    monkeypatch.setattr(job_service, "get_job", missing)
    response = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_malformed_job_id_is_422(client: TestClient) -> None:
    response = client.get("/api/v1/jobs/not-a-uuid")
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["path", "job_id"]


# ----------------------------------------------------------------- GET /jobs
def test_list_returns_summaries_without_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = [make_job(), make_job()]
    monkeypatch.setattr(job_service, "list_jobs", lambda *_a, **_k: (jobs, 42))
    response = client.get("/api/v1/jobs?limit=2&offset=4")
    body = response.json()
    assert response.status_code == 200
    assert (body["total"], body["limit"], body["offset"]) == (42, 2, 4)
    assert all(set(item) == SUMMARY_FIELDS for item in body["items"])
    assert "payload" not in response.text
    assert_no_internals(response.text)


def test_list_passes_filters_and_pagination_to_the_service(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake(_s: Any, filters: JobFilters, *, limit: int, offset: int) -> tuple[list[Job], int]:
        seen.update(filters=filters, limit=limit, offset=offset)
        return [], 0

    monkeypatch.setattr(job_service, "list_jobs", fake)
    client.get(
        "/api/v1/jobs",
        params={
            "status": "FAILED", "job_type": "report", "limit": 7, "offset": 14,
            "created_after": "2026-01-01T00:00:00Z", "created_before": "2026-02-01T00:00:00+00:00",
        },
    )  # fmt: skip
    filters = seen["filters"]
    assert (filters.status, filters.job_type) == (JobStatus.FAILED, JobType.REPORT)
    assert filters.created_after == datetime(2026, 1, 1, tzinfo=UTC)
    assert filters.created_before == datetime(2026, 2, 1, tzinfo=UTC)
    assert (seen["limit"], seen["offset"]) == (7, 14)


def test_list_defaults(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_service, "list_jobs", lambda *_a, **_k: ([], 0))
    body = client.get("/api/v1/jobs").json()
    assert (body["limit"], body["offset"], body["items"]) == (20, 0, [])


@pytest.mark.parametrize(
    "query",
    [
        "limit=0", "limit=101", "limit=abc", "offset=-1", "status=BOGUS", "status=failed",
        "job_type=nope", "created_after=2026-01-01T00:00:00",  # naive datetime
        "created_after=2026-02-01T00:00:00Z&created_before=2026-01-01T00:00:00Z",
        "created_after=yesterday", "sort=id",  # unknown parameter
    ],
)  # fmt: skip
def test_invalid_list_queries_are_422(client: TestClient, query: str) -> None:
    response = client.get(f"/api/v1/jobs?{query}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ------------------------------------------------------- GET /jobs/{id}/attempts
def test_attempts_hide_stack_trace_and_worker(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = uuid.uuid4()
    attempts = [make_attempt(job_id, 1), make_attempt(job_id, 2, status=AttemptStatus.SUCCEEDED)]
    monkeypatch.setattr(job_service, "list_attempts", lambda _s, _id: attempts)
    response = client.get(f"/api/v1/jobs/{job_id}/attempts")
    body = response.json()
    assert response.status_code == 200
    assert body["job_id"] == str(job_id)
    assert [a["attempt_number"] for a in body["items"]] == [1, 2]
    assert all(set(a) == ATTEMPT_FIELDS for a in body["items"])
    assert_no_internals(response.text)


def test_attempts_of_unknown_job_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(_s: Any, job_id: uuid.UUID) -> list[JobAttempt]:
        raise JobNotFoundError(job_id)

    monkeypatch.setattr(job_service, "list_attempts", missing)
    assert client.get(f"/api/v1/jobs/{uuid.uuid4()}/attempts").status_code == 404
