"""Data access for jobs. Repositories only talk SQL; they never commit (the service owns the
transaction) and contain no business rules."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rescueai.db.enums import JobStatus, JobType
from rescueai.db.models import Job


@dataclass(frozen=True)
class JobFilters:
    status: JobStatus | None = None
    job_type: JobType | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def insert_if_absent(self, values: dict[str, Any]) -> Job | None:
        """Insert a job; return it, or ``None`` if the idempotency key already exists.

        ``INSERT ... ON CONFLICT DO NOTHING`` is atomic: two concurrent requests with the same
        key cannot both insert, and the loser gets ``None`` instead of an exception (which would
        poison the surrounding transaction). If another transaction holds an uncommitted row
        with the same key, PostgreSQL makes this statement wait for it to finish first.
        """
        statement = (
            pg_insert(Job)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[Job.idempotency_key])
            .returning(Job)
        )
        return self._session.execute(statement).scalars().first()

    def get(self, job_id: uuid.UUID) -> Job | None:
        return self._session.get(Job, job_id)

    def get_by_idempotency_key(self, key: str) -> Job | None:
        return self._session.scalars(select(Job).where(Job.idempotency_key == key)).first()

    def list(self, filters: JobFilters, *, limit: int, offset: int) -> tuple[list[Job], int]:
        """Return (page of jobs, total matching). Newest first; ``id`` breaks timestamp ties so
        the order is total and pages are stable."""
        conditions = []
        if filters.status is not None:
            conditions.append(Job.status == filters.status)
        if filters.job_type is not None:
            conditions.append(Job.job_type == filters.job_type)
        if filters.created_after is not None:
            conditions.append(Job.created_at >= filters.created_after)
        if filters.created_before is not None:
            conditions.append(Job.created_at < filters.created_before)

        total = self._session.scalar(select(func.count()).select_from(Job).where(*conditions)) or 0
        items = self._session.scalars(
            select(Job)
            .where(*conditions)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return list(items), total
