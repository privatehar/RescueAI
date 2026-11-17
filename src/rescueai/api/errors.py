"""One error shape for the whole API::

    {"error": {"code": "...", "message": "...", "correlation_id": "...", "details": [...]}}

Rules: never echo request bodies back (validation errors drop pydantic's ``input``/``ctx``,
which can contain submitted values), and never leak internals (unexpected errors become a
generic 500 whose cause is only in the server logs).
"""

from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from rescueai.core.correlation import CORRELATION_HEADER
from rescueai.core.errors import AppError
from rescueai.core.logging import get_logger

logger = get_logger(__name__)

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "too_many_requests",
    503: "service_unavailable",
}


def _response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", None)
    body: dict[str, Any] = {"code": code, "message": message, "correlation_id": correlation_id}
    if details is not None:
        body["details"] = details
    response_headers = dict(headers or {})
    if correlation_id:
        # Needed explicitly: responses produced for unhandled exceptions bypass our middleware.
        response_headers[CORRELATION_HEADER] = correlation_id
    return JSONResponse({"error": body}, status_code=status_code, headers=response_headers)


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    error = cast(AppError, exc)
    return _response(request, error.status_code, error.code, error.message)


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    validation_error = cast(RequestValidationError, exc)
    details = [
        # Only location, message and type. NOT ``input`` (echoes what the client sent) or ``ctx``.
        {
            "loc": [str(part) if not isinstance(part, int) else part for part in error["loc"]],
            "msg": error["msg"],
            "type": error["type"],
        }
        for error in validation_error.errors()
    ]
    return _response(request, 422, "validation_error", "The request is invalid.", details=details)


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    http_error = cast(StarletteHTTPException, exc)
    code = _STATUS_CODES.get(http_error.status_code, "http_error")
    message = str(http_error.detail) if http_error.status_code < 500 else "An error occurred."
    return _response(
        request, http_error.status_code, code, message, headers=dict(http_error.headers or {})
    )


async def handle_database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logger.error("database_unavailable", error_type=type(exc).__name__)
    return _response(
        request,
        503,
        "service_unavailable",
        "The service is temporarily unavailable. Please retry shortly.",
        headers={"Retry-After": "5"},
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Details stay server-side (the traceback is logged by the ASGI server); the caller gets
    # only the correlation id to quote when reporting the problem.
    logger.error("unhandled_exception", error_type=type(exc).__name__, path=request.url.path)
    return _response(request, 500, "internal_error", "An unexpected error occurred.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(OperationalError, handle_database_unavailable)
    app.add_exception_handler(Exception, handle_unexpected_error)
