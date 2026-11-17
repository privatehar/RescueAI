"""Domain enumerations persisted by the data layer.

Adding a member here requires an Alembic migration that updates the matching CHECK constraint.
"""

from enum import StrEnum


class JobType(StrEnum):
    API_CALL = "api_call"
    ETL = "etl"
    REPORT = "report"


class JobStatus(StrEnum):
    PENDING = "PENDING"  # persisted, not yet handed to the queue
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    FAILED = "FAILED"  # permanent failure
    DEAD_LETTER = "DEAD_LETTER"  # retries exhausted
    CANCELLED = "CANCELLED"


# States in which a job has finished (a manual retry may still leave FAILED / DEAD_LETTER).
FINAL_STATUSES = (
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.DEAD_LETTER,
    JobStatus.CANCELLED,
)


class AttemptStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"  # worker crashed / lost; detected by the recovery sweeper
    TIMED_OUT = "TIMED_OUT"


class ActorType(StrEnum):
    SYSTEM = "SYSTEM"  # the platform itself (recovery engine, workers)
    USER = "USER"  # an authenticated person (once auth exists)
    ANONYMOUS = "ANONYMOUS"  # an unauthenticated API caller (before auth exists)


class AnalysisSource(StrEnum):
    LLM = "llm"
    FALLBACK = "fallback"  # deterministic analysis used when the LLM is unavailable


class RecoveryActionType(StrEnum):
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    DEAD_LETTERED = "DEAD_LETTERED"
    MARKED_FAILED = "MARKED_FAILED"
    MANUAL_RETRY = "MANUAL_RETRY"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    INTERRUPTED_RECOVERED = "INTERRUPTED_RECOVERED"
