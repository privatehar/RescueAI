"""Domain exceptions. The API layer maps them to HTTP responses (see ``api/errors.py``)."""


class AppError(Exception):
    """Base class for errors that are expected and safe to describe to API callers."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class JobNotFoundError(NotFoundError):
    def __init__(self, job_id: object) -> None:
        super().__init__(f"Job {job_id} was not found.")


class IdempotencyConflictError(ConflictError):
    code = "idempotency_conflict"

    def __init__(self) -> None:
        super().__init__(
            "This idempotency key was already used with a different request. "
            "Use a new key for a different job, or resend the original request unchanged."
        )
