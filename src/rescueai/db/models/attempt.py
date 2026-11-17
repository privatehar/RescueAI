import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from rescueai.db.base import Base, enum_column, in_list
from rescueai.db.enums import AttemptStatus


class JobAttempt(Base):
    """One execution attempt of a job. Rows are never deleted: this is the failure history."""

    __tablename__ = "job_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # RESTRICT (not CASCADE): deleting a job must never silently erase its history.
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[AttemptStatus] = mapped_column(enum_column(AttemptStatus, 20))
    error_type: Mapped[str | None] = mapped_column(String(200))
    error_message: Mapped[str | None] = mapped_column(Text)  # sanitized before storage
    stack_trace: Mapped[str | None] = mapped_column(Text)  # sanitized + truncated; never exposed
    retryable: Mapped[bool | None] = mapped_column(Boolean)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        # Also serves "attempts of job X in order" (leading column job_id).
        UniqueConstraint("job_id", "attempt_number", name="uq_job_attempts_job_id_attempt_number"),
        CheckConstraint(in_list("status", AttemptStatus), name="status_valid"),
        CheckConstraint("attempt_number >= 1", name="attempt_number_positive"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_non_negative"),
        # An attempt is "running" exactly while it has no finish time.
        CheckConstraint(
            "(status = 'RUNNING') = (finished_at IS NULL)", name="finished_at_matches_status"
        ),
        CheckConstraint(
            "status NOT IN ('FAILED', 'TIMED_OUT') OR error_type IS NOT NULL",
            name="failure_has_error_type",
        ),
        # Bound text columns so one pathological error cannot bloat the table.
        CheckConstraint(
            "error_message IS NULL OR char_length(error_message) <= 4000",
            name="error_message_length",
        ),
        CheckConstraint(
            "stack_trace IS NULL OR char_length(stack_trace) <= 20000",
            name="stack_trace_length",
        ),
    )


# At most one RUNNING attempt per job: a database-level guard against concurrent execution,
# independent of any Redis lock.
Index(
    "uq_job_attempts_one_running_per_job",
    JobAttempt.job_id,
    unique=True,
    postgresql_where=text("status = 'RUNNING'"),
)
