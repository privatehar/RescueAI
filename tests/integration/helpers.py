"""Raw-SQL helpers for integration tests.

Raw SQL (instead of the ORM) on purpose: the ORM validates enum values and fills defaults, which
would stop us from proving that the DATABASE itself rejects bad data.
"""

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

JSONB_COLUMNS = {"payload", "evidence", "details"}


def _insert(session: Session, table: str, columns: dict[str, Any]) -> uuid.UUID:
    names = list(columns)
    placeholders = [f"CAST(:{n} AS jsonb)" if n in JSONB_COLUMNS else f":{n}" for n in names]
    params = {n: json.dumps(v) if n in JSONB_COLUMNS else v for n, v in columns.items()}
    sql = (
        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(placeholders)}) RETURNING id"
    )
    result = session.execute(text(sql), params).scalar_one()
    assert isinstance(result, uuid.UUID)
    return result


def insert_job(session: Session, **overrides: Any) -> uuid.UUID:
    columns: dict[str, Any] = {
        "job_type": "etl",
        "payload": {"source_dataset": "a", "target_table": "b", "batch_size": 500},
        "request_hash": "a" * 64,
        "max_attempts": 5,
    }
    columns.update(overrides)
    return _insert(session, "jobs", columns)


def insert_attempt(session: Session, job_id: uuid.UUID, **overrides: Any) -> uuid.UUID:
    columns: dict[str, Any] = {
        "job_id": job_id,
        "attempt_number": 1,
        "status": "SUCCEEDED",
        "finished_at": datetime.now(UTC),
        "duration_ms": 10,
    }
    columns.update(overrides)
    return _insert(session, "job_attempts", columns)


def insert_analysis(session: Session, job_id: uuid.UUID, **overrides: Any) -> uuid.UUID:
    columns: dict[str, Any] = {
        "job_id": job_id,
        "source": "fallback",
        "category": "network_timeout",
        "root_cause": "Upstream did not answer in time.",
        "evidence": ["ConnectionTimeout x3"],
        "recommended_action": "Retry with backoff.",
        "confidence": 0.8,
        "requires_human_approval": False,
    }
    columns.update(overrides)
    return _insert(session, "failure_analyses", columns)


def insert_recovery_action(session: Session, job_id: uuid.UUID, **overrides: Any) -> uuid.UUID:
    columns: dict[str, Any] = {
        "job_id": job_id,
        "action_type": "RETRY_SCHEDULED",
        "actor_type": "SYSTEM",
        "to_status": "RETRY_SCHEDULED",
    }
    columns.update(overrides)
    return _insert(session, "recovery_actions", columns)


def insert_audit_event(session: Session, **overrides: Any) -> uuid.UUID:
    columns: dict[str, Any] = {
        "actor_type": "ANONYMOUS",
        "action": "job.created",
        "entity_type": "job",
        "entity_id": uuid.uuid4(),
    }
    columns.update(overrides)
    return _insert(session, "audit_events", columns)


def insert_outbox_event(session: Session, **overrides: Any) -> uuid.UUID:
    columns: dict[str, Any] = {
        "aggregate_type": "job",
        "aggregate_id": uuid.uuid4(),
        "event_type": "job.execute_requested",
        "payload": {},
    }
    columns.update(overrides)
    return _insert(session, "outbox_events", columns)


@contextmanager
def violates(session: Session, constraint: str) -> Iterator[None]:
    """Assert the block is rejected by the database *because of this specific constraint*.

    Matching the constraint name matters: it proves the intended rule fired, not just that
    "something" failed.
    """
    with pytest.raises((IntegrityError, DataError)) as excinfo:
        yield
    assert constraint in str(excinfo.value), (
        f"expected a violation of {constraint!r}, got: {str(excinfo.value)[:300]}"
    )
    session.rollback()  # the failed statement aborted the transaction


def count(session: Session, table: str) -> int:
    return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
