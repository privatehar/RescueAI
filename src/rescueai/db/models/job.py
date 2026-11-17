import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from rescueai.db.base import Base, enum_column, in_list
from rescueai.db.enums import FINAL_STATUSES, JobStatus, JobType

_FINAL = ", ".join(f"'{s.value}'" for s in FINAL_STATUSES)


class Job(Base):
    """A unit of background work. PostgreSQL is the source of truth for its state."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    job_type: Mapped[JobType] = mapped_column(enum_column(JobType, 32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # sha256 of the canonical (job_type, payload, requested max_attempts). Lets us tell an
    # idempotent replay apart from a different request that reuses an idempotency key.
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus, 20), server_default=text("'PENDING'")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer)
    # NULL is allowed many times: PostgreSQL treats NULLs as distinct in a UNIQUE constraint.
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    correlation_id: Mapped[str | None] = mapped_column(String(64))

    # Scheduling / crash-recovery fields. Written by later phases; defined now so the schema
    # (and its constraints) is stable.
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        CheckConstraint(in_list("job_type", JobType), name="job_type_valid"),
        CheckConstraint(in_list("status", JobStatus), name="status_valid"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
        CheckConstraint("char_length(request_hash) = 64", name="request_hash_length"),
        CheckConstraint(
            "idempotency_key IS NULL OR char_length(idempotency_key) BETWEEN 1 AND 128",
            name="idempotency_key_length",
        ),
        CheckConstraint("max_attempts BETWEEN 1 AND 10", name="max_attempts_range"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        CheckConstraint("attempt_count <= max_attempts", name="attempts_within_max"),
        # Final states must carry a completion time; non-final states must not.
        CheckConstraint(
            f"(status IN ({_FINAL})) = (completed_at IS NOT NULL)",
            name="completed_at_matches_final_status",
        ),
        CheckConstraint(
            "status <> 'RETRY_SCHEDULED' OR next_retry_at IS NOT NULL",
            name="retry_scheduled_has_next_retry_at",
        ),
        CheckConstraint(
            "started_at IS NULL OR completed_at IS NULL OR completed_at >= started_at",
            name="completed_after_started",
        ),
    )

    @property
    def duration_ms(self) -> int | None:
        """Execution time (started -> completed), when both are known."""
        if self.started_at is None or self.completed_at is None:
            return None
        return int((self.completed_at - self.started_at).total_seconds() * 1000)


# Serves the default listing (newest first) and keyset-style ordering; the (created_at, id)
# pair is a total order, so pages never skip or repeat rows that share a timestamp.
Index("ix_jobs_created_at_id", Job.created_at.desc(), Job.id.desc())
# Serves "list jobs with status X, newest first" without sorting.
Index("ix_jobs_status_created_at_id", Job.status, Job.created_at.desc(), Job.id.desc())
Index("ix_jobs_job_type_created_at_id", Job.job_type, Job.created_at.desc(), Job.id.desc())
