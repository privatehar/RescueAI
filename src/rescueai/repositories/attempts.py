import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from rescueai.db.models import JobAttempt


class AttemptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_job(self, job_id: uuid.UUID) -> list[JobAttempt]:
        """Attempts in execution order (served by the unique (job_id, attempt_number) index)."""
        return list(
            self._session.scalars(
                select(JobAttempt)
                .where(JobAttempt.job_id == job_id)
                .order_by(JobAttempt.attempt_number)
            )
        )
