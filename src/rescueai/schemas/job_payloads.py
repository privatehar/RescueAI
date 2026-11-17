"""Strictly-validated payloads for each job type.

Every model forbids unknown fields and uses strict types ("500" is not accepted for an int).
Payloads must never carry credentials: a job that needs a secret must reference it by name
(resolved server-side), not embed it. Payloads are stored and returned by the job-detail
endpoint, so anything placed here is visible to whoever can read the job.
"""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,64}$")]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ApiCallPayload(_StrictModel):
    """Simulates calling an external HTTP API."""

    url: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 10.0

    @field_validator("url")
    @classmethod
    def _http_url_without_credentials(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("url must be an absolute http(s) URL")
        if parts.username is not None or parts.password is not None:
            raise ValueError("url must not embed credentials")
        return value


class EtlPayload(_StrictModel):
    """Simulates an extract-transform-load run between two named datasets."""

    source_dataset: Identifier
    target_table: Identifier
    batch_size: Annotated[int, Field(ge=1, le=10_000)] = 500


class ReportPayload(_StrictModel):
    """Simulates generating a report."""

    report_type: Literal["daily_summary", "failure_summary", "job_stats"]
    period_days: Annotated[int, Field(ge=1, le=365)] = 7
    output_format: Literal["json", "csv"] = "json"
