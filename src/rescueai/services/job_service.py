"""Job use-cases. This layer owns the transaction boundary: one public function = one unit of
work, committed or rolled back as a whole. Repositories never commit."""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from rescueai.core.errors import IdempotencyConflictError, JobNotFoundError
from rescueai.db.enums import ActorType, JobStatus
from rescueai.db.models import Job, JobAttempt
from rescueai.repositories.attempts import AttemptRepository
from rescueai.repositories.audit import AuditRepository
from rescueai.repositories.jobs import JobFilters, JobRepository
from rescueai.repositories.outbox import OutboxRepository
from rescueai.schemas.job import JobCreateModel, request_fingerprint

# Normally one pass. A second pass is only needed if the row that blocked our INSERT vanished
# before we could read it (e.g. its transaction rolled back): then we simply try again.
_MAX_INSERT_PASSES = 3


@dataclass(frozen=True)
class CreateJobResult:
    job: Job
    created: bool  # False => an idempotent replay of an earlier identical request


def create_job(
    session: Session,
    request: JobCreateModel,
    *,
    correlation_id: str | None,
    default_max_attempts: int,
) -> CreateJobResult:
    """Persist a new job (status PENDING) together with its outbox event and audit record.

    The three rows are committed in ONE transaction: either the job exists *and* is guaranteed
    to be published later, or nothing exists. No worker is needed for this to succeed.

    Idempotency: same key + same request => the original job (``created=False``);
    same key + different request => ``IdempotencyConflictError``.
    """
    payload, request_hash = request_fingerprint(request)
    jobs = JobRepository(session)
    values = {
        "job_type": request.job_type,
        "payload": payload,
        "request_hash": request_hash,
        "status": JobStatus.PENDING,
        "max_attempts": request.max_attempts or default_max_attempts,
        "idempotency_key": request.idempotency_key,
        "correlation_id": correlation_id,
    }

    try:
        for _ in range(_MAX_INSERT_PASSES):
            job = jobs.insert_if_absent(values)
            if job is not None:
                OutboxRepository(session).add(
                    aggregate_type="job",
                    aggregate_id=job.id,
                    event_type="job.execute_requested",
                    payload={"job_id": str(job.id)},
                )
                AuditRepository(session).add(
                    actor_type=ActorType.ANONYMOUS,  # no authentication yet
                    actor_id=None,
                    action="job.created",
                    entity_type="job",
                    entity_id=job.id,
                    correlation_id=correlation_id,
                    # Never the payload: it may be sensitive, and audit rows are permanent.
                    details={"job_type": request.job_type},
                )
                session.commit()
                return CreateJobResult(job=job, created=True)

            # Insert was skipped, so the idempotency key already exists. (Without a key nothing
            # can conflict, so reaching here without one is a bug, not a client error.)
            if request.idempotency_key is None:
                raise RuntimeError("insert skipped for a job without an idempotency key")
            existing = jobs.get_by_idempotency_key(request.idempotency_key)
            if existing is None:
                continue
            if existing.request_hash != request_hash:
                raise IdempotencyConflictError
            return CreateJobResult(job=existing, created=False)
        raise RuntimeError("could not resolve idempotency key after retries")
    except Exception:
        session.rollback()
        raise


def get_job(session: Session, job_id: uuid.UUID) -> Job:
    job = JobRepository(session).get(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    return job


def list_jobs(
    session: Session, filters: JobFilters, *, limit: int, offset: int
) -> tuple[list[Job], int]:
    return JobRepository(session).list(filters, limit=limit, offset=offset)


def list_attempts(session: Session, job_id: uuid.UUID) -> list[JobAttempt]:
    get_job(session, job_id)  # 404 for an unknown job, instead of an empty list
    return AttemptRepository(session).list_for_job(job_id)
