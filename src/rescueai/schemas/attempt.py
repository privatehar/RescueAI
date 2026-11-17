import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from rescueai.db.enums import AttemptStatus


class AttemptResponse(BaseModel):
    """One execution attempt. ``stack_trace`` and ``worker_id`` are intentionally not exposed:
    traces reveal internal file paths and library versions, and worker ids reveal topology."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    attempt_number: int
    status: AttemptStatus
    error_type: str | None
    error_message: str | None
    retryable: bool | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None


class AttemptList(BaseModel):
    job_id: uuid.UUID
    items: list[AttemptResponse]
