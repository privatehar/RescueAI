"""Structured logging.

structlog is the front end; stdlib ``logging`` is the back end, so records from uvicorn and
other libraries are rendered the same way as ours. Context bound with
``structlog.contextvars`` (e.g. ``correlation_id``) is attached to every record automatically.
"""

import logging
import sys
from typing import Any, TextIO

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

REDACTED = "[REDACTED]"
_SENSITIVE_SUBSTRINGS = ("password", "passwd", "secret", "api_key", "apikey", "authorization")
_SENSITIVE_SUFFIXES = ("_token",)
_SENSITIVE_EXACT = {"token", "cookie", "set-cookie"}


# HTTP client libraries log every request URL (including query strings) at INFO. Outbound
# calls (e.g. to the OpenAI API) must not leak URLs or tokens into our logs, so keep them quiet.
_NOISY_LIBRARIES = ("httpx", "httpx2", "httpcore", "httpcore2")


def _is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return (
        lowered in _SENSITIVE_EXACT
        or lowered.endswith(_SENSITIVE_SUFFIXES)
        or any(part in lowered for part in _SENSITIVE_SUBSTRINGS)
    )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: REDACTED if _is_sensitive_key(k) else _redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(v) for v in value]
    return value


def redact_sensitive_keys(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Last line of defence: mask values whose *key* looks like a credential.

    This is key-based only. It cannot detect a secret embedded inside a free-text message,
    so callers must still avoid logging payloads. (Text sanitisation for the AI service
    is a separate, later piece of work.)
    """
    return dict(_redact(dict(event_dict)))


def configure_logging(
    *, level: str = "INFO", json_logs: bool = True, stream: TextIO | None = None
) -> None:
    """(Re)configure logging. ``stream`` defaults to stdout; tests inject their own buffer."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        redact_sensitive_keys,
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Route uvicorn through our handler. Access logging is done by our own middleware
    # (it knows the correlation id and deliberately omits query strings).
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    for name in _NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
