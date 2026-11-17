"""Correlation IDs and per-request access logging.

Every request gets a correlation ID: taken from the ``X-Correlation-ID`` header if the client
sent a safe-looking one, otherwise generated. It is bound into the logging context (so every
log line for the request carries it) and echoed in the response header. Later phases will
persist it on jobs so a single ID links the API call, the worker run and the AI analysis.

This is a pure ASGI middleware (not ``BaseHTTPMiddleware``) so contextvars behave correctly.
"""

import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rescueai.core.logging import get_logger

CORRELATION_HEADER = "X-Correlation-ID"
# Restrictive on purpose: the value is echoed in a response header and written to logs,
# so we reject anything that could enable header or log injection.
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

logger = get_logger(__name__)


def resolve_correlation_id(incoming: str | None) -> str:
    if incoming and _VALID_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = resolve_correlation_id(Headers(scope=scope).get(CORRELATION_HEADER))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        # Also on request.state: the contextvars are cleared when an exception unwinds through
        # this middleware, but the 500 handler (which runs after) still needs the id.
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        status_code = 500
        started = time.perf_counter()

        async def send_with_header(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[CORRELATION_HEADER] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            # Path only; the query string can carry tokens or PII and is never logged.
            logger.info(
                "request_completed",
                method=scope["method"],
                path=scope["path"],
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            structlog.contextvars.clear_contextvars()
