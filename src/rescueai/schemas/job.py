"""Request and response schemas for jobs."""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from rescueai.db.enums import JobStatus, JobType
from rescueai.schemas.job_payloads import ApiCallPayload, EtlPayload, ReportPayload

IdempotencyKey = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:\-]+$")
]
MaxAttempts = Annotated[int, Field(ge=1, le=10)]


# ---------------------------------------------------------------- requests
class _JobCreateBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    idempotency_key: IdempotencyKey | None = None
    max_attempts: MaxAttempts | None = None  # None => server default


class ApiCallJobCreate(_JobCreateBase):
    job_type: Literal["api_call"]
    payload: ApiCallPayload


class EtlJobCreate(_JobCreateBase):
    job_type: Literal["etl"]
    payload: EtlPayload


class ReportJobCreate(_JobCreateBase):
    job_type: Literal["report"]
    payload: ReportPayload


# A discriminated union: ``job_type`` selects which payload schema applies, so an unknown job
# type, or a payload that belongs to a different type, is rejected with a precise error.
JobCreate = Annotated[
    ApiCallJobCreate | EtlJobCreate | ReportJobCreate, Field(discriminator="job_type")
]
JobCreateModel = ApiCallJobCreate | EtlJobCreate | ReportJobCreate


def request_fingerprint(request: JobCreateModel) -> tuple[dict[str, object], str]:
    """Return (normalized payload, request hash).

    The payload is normalized (defaults filled in), so ``{"batch_size": 500}`` and an omitted
    batch size hash identically. The hash covers job type, payload and the *requested*
    ``max_attempts``; an idempotent replay must match all three.
    """
    payload = request.payload.model_dump(mode="json")
    canonical = json.dumps(
        {"job_type": request.job_type, "payload": payload, "max_attempts": request.max_attempts},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return payload, hashlib.sha256(canonical.encode()).hexdigest()


# ------------------------------------------------------------ query params
class JobListParams(BaseModel):
    """Filters and pagination for ``GET /jobs``. Unknown query parameters are rejected."""

    model_config = ConfigDict(extra="forbid")

    status: JobStatus | None = None
    job_type: JobType | None = None
    created_after: AwareDatetime | None = None  # timezone required: naive times are ambiguous
    created_before: AwareDatetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def _range_is_ordered(self) -> "JobListParams":
        if (
            self.created_after is not None
            and self.created_before is not None
            and self.created_after >= self.created_before
        ):
            raise ValueError("created_after must be earlier than created_before")
        return self


# --------------------------------------------------------------- responses
# Responses are explicit allow-lists: a column added to the model later is NOT exposed until
# someone adds it here. Never exposed: request_hash, locked_by/locked_at/heartbeat_at, version.
class JobSummary(BaseModel):
    """Compact job view for lists (no payload)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_type: JobType
    status: JobStatus
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None


class JobDetail(JobSummary):
    payload: dict[str, object]
    idempotency_key: str | None
    next_retry_at: datetime | None
    cancel_requested: bool
    correlation_id: str | None


class JobList(BaseModel):
    items: list[JobSummary]
    total: int
    limit: int
    offset: int
