import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response

from rescueai.api.deps import SessionDep
from rescueai.core.config import get_settings
from rescueai.repositories.jobs import JobFilters
from rescueai.schemas.attempt import AttemptList, AttemptResponse
from rescueai.schemas.common import ErrorResponse
from rescueai.schemas.job import JobCreate, JobDetail, JobList, JobListParams, JobSummary
from rescueai.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Job not found"}
}


@router.post(
    "",
    status_code=202,
    response_model=JobDetail,
    summary="Submit a job",
    responses={
        200: {"model": JobDetail, "description": "Idempotent replay: the existing job"},
        409: {
            "model": ErrorResponse,
            "description": "Idempotency key reused with a different request",
        },
        422: {"model": ErrorResponse, "description": "Invalid request"},
    },
)
def create_job(
    body: JobCreate, request: Request, response: Response, session: SessionDep
) -> JobDetail:
    """Persist a job and return **202 Accepted** (it is accepted for later asynchronous work).

    Send an `idempotency_key` to make retries of this call safe: the same key with the same
    request returns the original job (**200**, header `Idempotent-Replayed: true`); the same key
    with a different request is rejected with **409**.
    """
    result = job_service.create_job(
        session,
        body,
        correlation_id=getattr(request.state, "correlation_id", None),
        default_max_attempts=get_settings().default_max_attempts,
    )
    if result.created:
        response.headers["Location"] = f"/api/v1/jobs/{result.job.id}"
    else:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return JobDetail.model_validate(result.job)


@router.get("", response_model=JobList, summary="List jobs")
def list_jobs(params: Annotated[JobListParams, Query()], session: SessionDep) -> JobList:
    """Newest first. Filter by status, job type and creation time; paginate with limit/offset."""
    jobs, total = job_service.list_jobs(
        session,
        JobFilters(
            status=params.status,
            job_type=params.job_type,
            created_after=params.created_after,
            created_before=params.created_before,
        ),
        limit=params.limit,
        offset=params.offset,
    )
    return JobList(
        items=[JobSummary.model_validate(job) for job in jobs],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/{job_id}", response_model=JobDetail, responses=_NOT_FOUND, summary="Get a job")
def get_job(job_id: uuid.UUID, session: SessionDep) -> JobDetail:
    return JobDetail.model_validate(job_service.get_job(session, job_id))


@router.get(
    "/{job_id}/attempts",
    response_model=AttemptList,
    responses=_NOT_FOUND,
    summary="Execution attempt history of a job",
)
def list_attempts(job_id: uuid.UUID, session: SessionDep) -> AttemptList:
    attempts = job_service.list_attempts(session, job_id)
    return AttemptList(job_id=job_id, items=[AttemptResponse.model_validate(a) for a in attempts])
