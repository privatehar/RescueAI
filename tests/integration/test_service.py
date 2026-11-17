"""Job service against real PostgreSQL: transactions, atomicity, idempotency, concurrency."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.orm import Session

from rescueai.core.errors import IdempotencyConflictError, JobNotFoundError
from rescueai.db.enums import ActorType, JobStatus, JobType
from rescueai.db.session import get_sessionmaker
from rescueai.repositories.audit import AuditRepository
from rescueai.repositories.outbox import OutboxRepository
from rescueai.schemas.job import JobCreate, JobCreateModel
from rescueai.services import job_service
from rescueai.services.job_service import CreateJobResult, create_job
from tests.integration.helpers import count, insert_attempt, insert_job

pytestmark = pytest.mark.integration

ADAPTER: TypeAdapter[JobCreateModel] = TypeAdapter(JobCreate)


def request(**overrides: Any) -> JobCreateModel:
    data: dict[str, Any] = {
        "job_type": "etl",
        "payload": {"source_dataset": "orders", "target_table": "dw_orders"},
    }
    data.update(overrides)
    return ADAPTER.validate_python(data)


def create(**overrides: Any) -> CreateJobResult:
    """Run the service the way the API does: its own session, closed afterwards."""
    with get_sessionmaker()() as work_session:
        return create_job(
            work_session, request(**overrides), correlation_id="corr-1", default_max_attempts=5
        )


def counts(session: Session) -> tuple[int, int, int]:
    session.rollback()  # fresh snapshot
    return count(session, "jobs"), count(session, "outbox_events"), count(session, "audit_events")


# ------------------------------------------------------------------ create
def test_create_persists_a_pending_job_with_defaults(app_db: str, session: Session) -> None:
    result = create()
    assert result.created is True

    row = session.execute(
        text(
            "SELECT job_type, status, attempt_count, max_attempts, correlation_id, "
            "payload, idempotency_key, created_at FROM jobs WHERE id = :i"
        ),
        {"i": result.job.id},
    ).one()
    assert row.job_type == "etl"
    assert row.status == "PENDING"
    assert row.attempt_count == 0
    assert row.max_attempts == 5  # server default applied
    assert row.correlation_id == "corr-1"
    assert row.payload == {
        "source_dataset": "orders",
        "target_table": "dw_orders",
        "batch_size": 500,
    }
    assert row.idempotency_key is None
    assert row.created_at.utcoffset() == timedelta(0)


def test_create_honours_requested_max_attempts(app_db: str) -> None:
    assert create(max_attempts=3).job.max_attempts == 3


def test_create_writes_job_outbox_and_audit_in_one_commit(app_db: str, session: Session) -> None:
    job = create(idempotency_key="k-1").job

    assert counts(session) == (1, 1, 1)
    outbox = session.execute(text("SELECT * FROM outbox_events")).one()
    assert (outbox.aggregate_type, outbox.aggregate_id) == ("job", job.id)
    assert outbox.event_type == "job.execute_requested"
    assert outbox.payload == {"job_id": str(job.id)}
    assert outbox.published_at is None  # nothing publishes yet; the relay is a later phase

    audit = session.execute(text("SELECT * FROM audit_events")).one()
    assert (audit.action, audit.entity_type, audit.entity_id) == ("job.created", "job", job.id)
    assert audit.actor_type == ActorType.ANONYMOUS
    assert audit.correlation_id == "corr-1"
    assert audit.details == {"job_type": "etl"}  # the payload is never copied into the audit log


def test_audit_log_never_contains_the_payload(app_db: str, session: Session) -> None:
    create(payload={"source_dataset": "very_private_dataset", "target_table": "t"})
    dump = session.execute(text("SELECT details::text FROM audit_events")).scalar_one()
    assert "very_private_dataset" not in dump


def test_identical_requests_without_a_key_create_separate_jobs(
    app_db: str, session: Session
) -> None:
    first, second = create(), create()
    assert first.job.id != second.job.id
    assert counts(session) == (2, 2, 2)


# ------------------------------------------------------------ atomicity
@pytest.mark.parametrize("failing", [OutboxRepository, AuditRepository])
def test_failure_after_the_job_insert_rolls_everything_back(
    app_db: str, session: Session, monkeypatch: pytest.MonkeyPatch, failing: type
) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("simulated failure mid-transaction")

    monkeypatch.setattr(failing, "add", boom)
    with pytest.raises(RuntimeError, match="simulated"):
        create(idempotency_key="k-atomic")
    assert counts(session) == (0, 0, 0)  # no orphan job without its outbox event


def test_a_failed_create_does_not_burn_the_idempotency_key(
    app_db: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(
            OutboxRepository, "add", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError())
        )
        with pytest.raises(RuntimeError):
            create(idempotency_key="retry-me")
    result = create(idempotency_key="retry-me")  # the client retries; it must now succeed
    assert result.created is True
    assert counts(session) == (1, 1, 1)


# ------------------------------------------------------------ idempotency
def test_same_key_same_request_is_a_replay(app_db: str, session: Session) -> None:
    first = create(idempotency_key="order-42")
    second = create(idempotency_key="order-42")
    assert (first.created, second.created) == (True, False)
    assert second.job.id == first.job.id
    assert counts(session) == (1, 1, 1)  # no second job, outbox event or audit record


def test_replay_returns_the_jobs_current_state(app_db: str, session: Session) -> None:
    first = create(idempotency_key="order-43")
    session.execute(text("UPDATE jobs SET status = 'QUEUED' WHERE id = :i"), {"i": first.job.id})
    session.commit()
    assert create(idempotency_key="order-43").job.status == JobStatus.QUEUED


def test_explicit_default_equals_omitted_default(app_db: str) -> None:
    omitted = create(idempotency_key="d")
    explicit = create(
        idempotency_key="d",
        payload={"source_dataset": "orders", "target_table": "dw_orders", "batch_size": 500},
    )
    assert explicit.created is False
    assert explicit.job.id == omitted.job.id


@pytest.mark.parametrize(
    "different",
    [
        {"payload": {"source_dataset": "other", "target_table": "dw_orders"}},
        {"max_attempts": 2},
        {"job_type": "report", "payload": {"report_type": "job_stats"}},
    ],
)
def test_same_key_different_request_is_a_conflict(
    app_db: str, session: Session, different: dict[str, Any]
) -> None:
    create(idempotency_key="shared")
    with pytest.raises(IdempotencyConflictError):
        create(idempotency_key="shared", **different)
    assert counts(session) == (1, 1, 1)  # the conflicting request wrote nothing


def test_different_keys_create_different_jobs(app_db: str) -> None:
    assert create(idempotency_key="a").job.id != create(idempotency_key="b").job.id


# ------------------------------------------------------------ concurrency
def _race(requests: list[JobCreateModel]) -> list[CreateJobResult | IdempotencyConflictError]:
    """Fire all requests at the same instant, each in its own session/connection."""
    barrier = threading.Barrier(len(requests))

    def worker(item: JobCreateModel) -> CreateJobResult | IdempotencyConflictError:
        with get_sessionmaker()() as work_session:
            barrier.wait()
            try:
                return create_job(work_session, item, correlation_id=None, default_max_attempts=5)
            except IdempotencyConflictError as error:
                return error

    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        return list(pool.map(worker, requests))


def test_concurrent_identical_requests_create_exactly_one_job(
    app_db: str, session: Session
) -> None:
    results = _race([request(idempotency_key="race-1") for _ in range(12)])

    outcomes = [r for r in results if isinstance(r, CreateJobResult)]
    assert len(outcomes) == 12  # nobody got an error (no IntegrityError leaked out)
    assert sum(r.created for r in outcomes) == 1  # exactly one winner
    assert len({r.job.id for r in outcomes}) == 1  # everyone sees the same job
    assert counts(session) == (1, 1, 1)


def test_concurrent_conflicting_requests_never_create_two_jobs(
    app_db: str, session: Session
) -> None:
    mine = request(idempotency_key="race-2")
    other = request(idempotency_key="race-2", max_attempts=2)
    results = _race([mine, other] * 6)

    created = [r for r in results if isinstance(r, CreateJobResult) and r.created]
    conflicts = [r for r in results if isinstance(r, IdempotencyConflictError)]
    replays = [r for r in results if isinstance(r, CreateJobResult) and not r.created]
    assert len(created) == 1
    assert len(conflicts) + len(replays) == 11
    assert len(conflicts) == 6  # all six of the losing variant are rejected
    assert counts(session) == (1, 1, 1)


def test_concurrent_distinct_requests_all_succeed(app_db: str, session: Session) -> None:
    results = _race([request(idempotency_key=f"distinct-{i}") for i in range(10)])
    assert all(isinstance(r, CreateJobResult) and r.created for r in results)
    assert counts(session) == (10, 10, 10)


# --------------------------------------------------------------- read paths
def test_get_job_not_found(app_db: str) -> None:
    with get_sessionmaker()() as work_session, pytest.raises(JobNotFoundError):
        job_service.get_job(work_session, uuid.uuid4())


def test_list_attempts_for_unknown_job_is_not_found_not_empty(app_db: str) -> None:
    with get_sessionmaker()() as work_session, pytest.raises(JobNotFoundError):
        job_service.list_attempts(work_session, uuid.uuid4())


def test_list_attempts_are_in_execution_order(app_db: str, session: Session) -> None:
    job_id = insert_job(session)
    for number in (3, 1, 2):  # inserted out of order on purpose
        insert_attempt(session, job_id, attempt_number=number, status="FAILED", error_type="E")
    session.commit()
    with get_sessionmaker()() as work_session:
        attempts = job_service.list_attempts(work_session, job_id)
    assert [a.attempt_number for a in attempts] == [1, 2, 3]


def test_job_type_enum_roundtrips_from_the_database(app_db: str) -> None:
    result = create(job_type="report", payload={"report_type": "job_stats"})
    with get_sessionmaker()() as work_session:
        assert job_service.get_job(work_session, result.job.id).job_type is JobType.REPORT
