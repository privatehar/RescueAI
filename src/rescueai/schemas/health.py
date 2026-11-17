from typing import Literal

from pydantic import BaseModel


class CheckResult(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float | None = None
    # Exception *class name* only. Messages can contain hostnames or credentials, so they go
    # to the (server-side) logs and never into the response.
    error_type: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, CheckResult]
