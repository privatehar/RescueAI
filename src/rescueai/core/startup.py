"""Startup dependency wait: bounded retries with exponential backoff, then fail fast.

Why not retry forever? A service that silently waits forever looks "up" to humans but does
nothing. Why not fail on the first attempt? PostgreSQL commonly needs a few seconds after
the container starts. So: retry for a bounded window, log each attempt, then raise a clear error
so the process exits non-zero and the orchestrator (Docker ``restart: unless-stopped``,
Kubernetes, ...) applies its own restart/backoff policy.
"""

import time
from collections.abc import Callable, Mapping

from rescueai.core.logging import get_logger

logger = get_logger(__name__)

Probe = Callable[[], None]


class StartupError(RuntimeError):
    """Raised when required dependencies are still unavailable after the wait budget."""


def wait_for_dependencies(
    probes: Mapping[str, Probe],
    *,
    max_wait_seconds: float,
    initial_delay_seconds: float = 0.5,
    max_delay_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Block until every probe succeeds, or raise ``StartupError`` once the budget is spent.

    Every probe is attempted at least once even when ``max_wait_seconds`` is 0. ``sleep`` and
    ``monotonic`` are injectable so the retry logic can be tested without real waiting.
    """
    deadline = monotonic() + max_wait_seconds
    pending: dict[str, Probe] = dict(probes)
    last_error: dict[str, str] = {}
    delay = initial_delay_seconds
    attempt = 0

    while True:
        attempt += 1
        for name, probe in list(pending.items()):
            try:
                probe()
            except Exception as exc:
                last_error[name] = type(exc).__name__
                logger.warning(
                    "dependency_unavailable",
                    dependency=name,
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
            else:
                del pending[name]
                logger.info("dependency_ready", dependency=name, attempt=attempt)

        if not pending:
            return

        remaining = deadline - monotonic()
        if remaining <= 0:
            details = ", ".join(f"{n} ({last_error[n]})" for n in pending)
            raise StartupError(
                f"Dependencies not ready after {max_wait_seconds:g}s and {attempt} attempt(s): "
                f"{details}. Check that PostgreSQL and Redis are running and that DATABASE_URL / "
                "REDIS_URL are correct."
            )
        sleep(min(delay, remaining))
        delay = min(delay * 2, max_delay_seconds)
