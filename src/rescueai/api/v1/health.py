import time

from fastapi import APIRouter, Response, status

from rescueai import __version__
from rescueai.api.deps import DatabaseProbe, HealthProbe, RedisProbe
from rescueai.core.logging import get_logger
from rescueai.schemas.health import CheckResult, HealthResponse

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


def _run_probe(name: str, probe: HealthProbe) -> CheckResult:
    started = time.perf_counter()
    try:
        probe()
    except Exception as exc:
        # Broad on purpose: any failure of a dependency means "not healthy".
        logger.warning(
            "health_probe_failed",
            dependency=name,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        return CheckResult(status="error", error_type=type(exc).__name__)
    return CheckResult(status="ok", latency_ms=round((time.perf_counter() - started) * 1000, 2))


@router.get(
    "/health",
    response_model=HealthResponse,
    response_model_exclude_none=True,
    responses={503: {"model": HealthResponse, "description": "A dependency is unhealthy"}},
)
def health(
    response: Response,
    database_probe: DatabaseProbe,
    redis_probe: RedisProbe,
) -> HealthResponse:
    """Report API, PostgreSQL and Redis status.

    Returns 503 when any dependency is down so load balancers and Docker healthchecks can act
    on the status code alone. Probes run sequentially, so the worst case is about
    2 x HEALTH_CHECK_TIMEOUT_SECONDS.
    """
    checks = {
        "api": CheckResult(status="ok"),
        "database": _run_probe("database", database_probe),
        "redis": _run_probe("redis", redis_probe),
    }
    healthy = all(check.status == "ok" for check in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded", version=__version__, checks=checks
    )
