"""Every important database rule, proven against real PostgreSQL.

Each case checks the NAMED constraint that fired (see ``violates``), so a test cannot pass by
accident because some unrelated error occurred.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.integration.helpers import (
    insert_analysis,
    insert_attempt,
    insert_audit_event,
    insert_job,
    insert_outbox_event,
    insert_recovery_action,
    violates,
)

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


# ------------------------------------------------------------------- jobs
def test_valid_job_gets_sensible_server_side_defaults(session: Session) -> None:
    job_id = insert_job(session)
    row = session.execute(
        text(
            "SELECT status, attempt_count, cancel_requested, version, created_at, updated_at, "
            "pg_typeof(id)::text, current_setting('TimeZone') FROM jobs WHERE id = :id"
        ),
        {"id": job_id},
    ).one()
    assert row[0] == "PENDING"
    assert row[1] == 0
    assert row[2] is False
    assert row[3] == 1
    assert row[4].utcoffset() == timedelta(0)  # timestamps come back in UTC
    assert row[5] is not None
    assert row[6] == "uuid"
    assert row[7] == "UTC"


JOB_VIOLATIONS: list[tuple[str, dict[str, Any], str]] = [
    ("invalid status", {"status": "BOGUS"}, "ck_jobs_status_valid"),
    ("lowercase status", {"status": "pending"}, "ck_jobs_status_valid"),
    ("invalid job type", {"job_type": "shell"}, "ck_jobs_job_type_valid"),
    ("short request hash", {"request_hash": "abc"}, "ck_jobs_request_hash_length"),
    ("max_attempts zero", {"max_attempts": 0}, "ck_jobs_max_attempts_range"),
    ("max_attempts eleven", {"max_attempts": 11}, "ck_jobs_max_attempts_range"),
    ("negative attempt_count", {"attempt_count": -1}, "ck_jobs_attempt_count_non_negative"),
    ("attempts beyond max", {"attempt_count": 6, "max_attempts": 5}, "ck_jobs_attempts_within_max"),
    ("empty idempotency key", {"idempotency_key": ""}, "ck_jobs_idempotency_key_length"),
    (
        "completed_at on a non-final job",
        {"status": "RUNNING", "completed_at": NOW},
        "ck_jobs_completed_at_matches_final_status",
    ),
    (
        "final job without completed_at",
        {"status": "SUCCEEDED"},
        "ck_jobs_completed_at_matches_final_status",
    ),
    (
        "retry scheduled without next_retry_at",
        {"status": "RETRY_SCHEDULED"},
        "ck_jobs_retry_scheduled_has_next_retry_at",
    ),
    (
        "completed before started",
        {"status": "SUCCEEDED", "started_at": NOW, "completed_at": NOW - timedelta(hours=1)},
        "ck_jobs_completed_after_started",
    ),
]


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [pytest.param(o, c, id=name) for name, o, c in JOB_VIOLATIONS],
)
def test_job_rule_is_enforced_by_the_database(
    session: Session, overrides: dict[str, Any], constraint: str
) -> None:
    with violates(session, constraint):
        insert_job(session, **overrides)


def test_job_payload_must_be_a_json_object(session: Session) -> None:
    with violates(session, "ck_jobs_payload_is_object"):
        insert_job(session, payload=["not", "an", "object"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "SUCCEEDED", "completed_at": NOW},
        {"status": "FAILED", "completed_at": NOW},
        {"status": "DEAD_LETTER", "completed_at": NOW, "attempt_count": 5},
        {"status": "CANCELLED", "completed_at": NOW},
        {"status": "RETRY_SCHEDULED", "next_retry_at": NOW + timedelta(seconds=30)},
        {"status": "RUNNING", "started_at": NOW},
    ],
)
def test_legal_job_states_are_accepted(session: Session, overrides: dict[str, Any]) -> None:
    insert_job(session, **overrides)  # must not raise


def test_idempotency_key_is_unique(session: Session) -> None:
    insert_job(session, idempotency_key="order-1")
    with violates(session, "uq_jobs_idempotency_key"):
        insert_job(session, idempotency_key="order-1")


def test_many_jobs_without_idempotency_key_are_allowed(session: Session) -> None:
    for _ in range(3):
        insert_job(session, idempotency_key=None)  # NULLs never collide


# --------------------------------------------------------------- attempts
def test_attempt_numbers_are_unique_per_job(session: Session) -> None:
    job_id = insert_job(session)
    insert_attempt(session, job_id, attempt_number=1)
    with violates(session, "uq_job_attempts_job_id_attempt_number"):
        insert_attempt(session, job_id, attempt_number=1)


def test_same_attempt_number_is_fine_for_different_jobs(session: Session) -> None:
    insert_attempt(session, insert_job(session), attempt_number=1)
    insert_attempt(session, insert_job(session), attempt_number=1)


def test_only_one_running_attempt_per_job(session: Session) -> None:
    job_id = insert_job(session)
    insert_attempt(
        session, job_id, attempt_number=1, status="RUNNING", finished_at=None, duration_ms=None
    )
    with violates(session, "uq_job_attempts_one_running_per_job"):
        insert_attempt(
            session, job_id, attempt_number=2, status="RUNNING", finished_at=None, duration_ms=None
        )


def test_a_new_attempt_may_run_after_the_previous_one_finished(session: Session) -> None:
    job_id = insert_job(session)
    insert_attempt(session, job_id, attempt_number=1, status="FAILED", error_type="Timeout")
    insert_attempt(
        session, job_id, attempt_number=2, status="RUNNING", finished_at=None, duration_ms=None
    )


ATTEMPT_VIOLATIONS: list[tuple[str, dict[str, Any], str]] = [
    ("invalid status", {"status": "EXPLODED"}, "ck_job_attempts_status_valid"),
    ("attempt number zero", {"attempt_number": 0}, "ck_job_attempts_attempt_number_positive"),
    ("negative duration", {"duration_ms": -5}, "ck_job_attempts_duration_non_negative"),
    (
        "running but has finish time",
        {"status": "RUNNING", "finished_at": NOW},
        "ck_job_attempts_finished_at_matches_status",
    ),
    (
        "finished but no finish time",
        {"status": "SUCCEEDED", "finished_at": None},
        "ck_job_attempts_finished_at_matches_status",
    ),
    ("failed without error type", {"status": "FAILED"}, "ck_job_attempts_failure_has_error_type"),
    (
        "timed out without error type",
        {"status": "TIMED_OUT"},
        "ck_job_attempts_failure_has_error_type",
    ),
    (
        "oversized error message",
        {"status": "FAILED", "error_type": "E", "error_message": "x" * 4001},
        "ck_job_attempts_error_message_length",
    ),
    (
        "oversized stack trace",
        {"status": "FAILED", "error_type": "E", "stack_trace": "x" * 20001},
        "ck_job_attempts_stack_trace_length",
    ),
]


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [pytest.param(o, c, id=name) for name, o, c in ATTEMPT_VIOLATIONS],
)
def test_attempt_rule_is_enforced_by_the_database(
    session: Session, overrides: dict[str, Any], constraint: str
) -> None:
    job_id = insert_job(session)
    with violates(session, constraint):
        insert_attempt(session, job_id, **overrides)


def test_attempt_requires_an_existing_job(session: Session) -> None:
    with violates(session, "fk_job_attempts_job_id_jobs"):
        insert_attempt(session, uuid.uuid4())


def test_message_at_the_size_limit_is_accepted(session: Session) -> None:
    job_id = insert_job(session)
    insert_attempt(
        session, job_id, status="FAILED", error_type="E",
        error_message="x" * 4000, stack_trace="y" * 20000,
    )  # fmt: skip


# ---------------------------------------------------------------- analyses
def test_valid_llm_and_fallback_analyses_are_accepted(session: Session) -> None:
    job_id = insert_job(session)
    insert_analysis(session, job_id, source="llm", model_name="gpt-test", confidence=1)
    insert_analysis(session, job_id, source="fallback", model_name=None, confidence=0)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"confidence": 1.5}, "ck_failure_analyses_confidence_range"),
        ({"confidence": -0.1}, "ck_failure_analyses_confidence_range"),
        ({"source": "oracle"}, "ck_failure_analyses_source_valid"),
        ({"source": "llm", "model_name": None}, "ck_failure_analyses_llm_analysis_has_model_name"),
        ({"evidence": {"not": "a list"}}, "ck_failure_analyses_evidence_is_array"),
        ({"input_tokens": -1}, "ck_failure_analyses_token_counts_non_negative"),
    ],
)
def test_analysis_rule_is_enforced_by_the_database(
    session: Session, overrides: dict[str, Any], constraint: str
) -> None:
    job_id = insert_job(session)
    with violates(session, constraint):
        insert_analysis(session, job_id, **overrides)


def test_analysis_requires_an_existing_job_and_attempt(session: Session) -> None:
    with violates(session, "fk_failure_analyses_job_id_jobs"):
        insert_analysis(session, uuid.uuid4())
    job_id = insert_job(session)
    with violates(session, "fk_failure_analyses_attempt_id_job_attempts"):
        insert_analysis(session, job_id, attempt_id=uuid.uuid4())


# --------------------------------------------------------- recovery actions
def test_valid_recovery_actions_are_accepted(session: Session) -> None:
    job_id = insert_job(session)
    insert_recovery_action(session, job_id, actor_type="SYSTEM")
    insert_recovery_action(
        session, job_id, actor_type="USER", actor_id="alice", action_type="MANUAL_RETRY"
    )


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"action_type": "TELEPORT"}, "ck_recovery_actions_action_type_valid"),
        ({"actor_type": "ROBOT"}, "ck_recovery_actions_actor_type_valid"),
        ({"to_status": "LIMBO"}, "ck_recovery_actions_to_status_valid"),
        ({"from_status": "LIMBO"}, "ck_recovery_actions_from_status_valid"),
        ({"actor_type": "USER", "actor_id": None}, "ck_recovery_actions_user_has_actor_id"),
        ({"details": ["x"]}, "ck_recovery_actions_details_is_object"),
    ],
)
def test_recovery_action_rule_is_enforced_by_the_database(
    session: Session, overrides: dict[str, Any], constraint: str
) -> None:
    job_id = insert_job(session)
    with violates(session, constraint):
        insert_recovery_action(session, job_id, **overrides)


def test_recovery_action_requires_existing_references(session: Session) -> None:
    with violates(session, "fk_recovery_actions_job_id_jobs"):
        insert_recovery_action(session, uuid.uuid4())
    job_id = insert_job(session)
    with violates(session, "fk_recovery_actions_analysis_id_failure_analyses"):
        insert_recovery_action(session, job_id, analysis_id=uuid.uuid4())


# --------------------------------------------------------------- audit log
def test_audit_events_can_be_inserted(session: Session) -> None:
    insert_audit_event(session, details={"job_type": "etl"})


def test_audit_events_reject_invalid_actor(session: Session) -> None:
    with violates(session, "ck_audit_events_actor_type_valid"):
        insert_audit_event(session, actor_type="GHOST")


def test_audit_events_cannot_be_updated(session: Session) -> None:
    event_id = insert_audit_event(session)
    session.commit()
    with violates(session, "append-only"):
        session.execute(
            text("UPDATE audit_events SET action = 'tampered' WHERE id = :i"), {"i": event_id}
        )
    action = session.execute(
        text("SELECT action FROM audit_events WHERE id = :i"), {"i": event_id}
    ).scalar_one()
    assert action == "job.created"


def test_audit_events_cannot_be_deleted(session: Session) -> None:
    event_id = insert_audit_event(session)
    session.commit()
    with violates(session, "append-only"):
        session.execute(text("DELETE FROM audit_events WHERE id = :i"), {"i": event_id})
    remaining = session.execute(
        text("SELECT count(*) FROM audit_events WHERE id = :i"), {"i": event_id}
    ).scalar_one()
    assert remaining == 1


# ------------------------------------------------------------------ outbox
def test_outbox_rejects_negative_attempts_and_non_object_payload(session: Session) -> None:
    with violates(session, "ck_outbox_events_publish_attempts_non_negative"):
        insert_outbox_event(session, publish_attempts=-1)
    with violates(session, "ck_outbox_events_payload_is_object"):
        insert_outbox_event(session, payload=[1])


def test_outbox_event_defaults_to_unpublished(session: Session) -> None:
    event_id = insert_outbox_event(session)
    row = session.execute(
        text("SELECT published_at, publish_attempts FROM outbox_events WHERE id = :i"),
        {"i": event_id},
    ).one()
    assert row[0] is None
    assert row[1] == 0


# ----------------------------------------------------------- history is kept
def test_deleting_a_job_with_history_is_refused(session: Session) -> None:
    job_id = insert_job(session)
    insert_attempt(session, job_id, status="FAILED", error_type="Timeout")
    session.commit()
    with violates(session, "fk_job_attempts_job_id_jobs"):
        session.execute(text("DELETE FROM jobs WHERE id = :i"), {"i": job_id})


def test_a_job_without_history_can_be_deleted(session: Session) -> None:
    job_id = insert_job(session)
    session.execute(text("DELETE FROM jobs WHERE id = :i"), {"i": job_id})
