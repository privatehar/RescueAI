"""JobRepository against real PostgreSQL: pagination, filters, ordering, index usage."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from rescueai.db.enums import JobStatus, JobType
from rescueai.repositories.jobs import JobFilters, JobRepository
from tests.integration.helpers import insert_attempt, insert_job

pytestmark = pytest.mark.integration

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def seed(session: Session, count: int, **overrides: object) -> list[uuid.UUID]:
    """Insert ``count`` jobs one minute apart (oldest first) and commit."""
    ids = [
        insert_job(session, created_at=BASE + timedelta(minutes=i), **overrides)
        for i in range(count)
    ]
    session.commit()
    return ids


def test_newest_first_ordering(session: Session) -> None:
    ids = seed(session, 5)
    jobs, total = JobRepository(session).list(JobFilters(), limit=10, offset=0)
    assert [j.id for j in jobs] == list(reversed(ids))
    assert total == 5


def test_pagination_pages_are_complete_and_disjoint(session: Session) -> None:
    ids = seed(session, 25)
    repo = JobRepository(session)
    pages = [repo.list(JobFilters(), limit=10, offset=o) for o in (0, 10, 20)]

    assert [len(items) for items, _ in pages] == [10, 10, 5]
    assert {total for _, total in pages} == {25}  # total is independent of the page
    seen = [job.id for items, _ in pages for job in items]
    assert len(seen) == len(set(seen)) == 25  # no duplicates, nothing skipped
    assert seen == list(reversed(ids))


def test_offset_beyond_the_end_returns_empty_page_but_correct_total(session: Session) -> None:
    seed(session, 3)
    jobs, total = JobRepository(session).list(JobFilters(), limit=10, offset=50)
    assert jobs == []
    assert total == 3


def test_empty_table(session: Session) -> None:
    assert JobRepository(session).list(JobFilters(), limit=10, offset=0) == ([], 0)


def test_rows_with_identical_timestamps_page_deterministically(session: Session) -> None:
    ids = [insert_job(session, created_at=BASE) for _ in range(7)]  # all tied
    session.commit()
    repo = JobRepository(session)
    paged = [j.id for o in (0, 2, 4, 6) for j in repo.list(JobFilters(), limit=2, offset=o)[0]]
    assert len(paged) == len(set(paged)) == 7  # the id tie-breaker prevents skips/repeats
    assert paged == sorted(ids, reverse=True)


def test_filter_by_status(session: Session) -> None:
    seed(session, 3, status="PENDING")
    seed(session, 2, status="QUEUED")
    jobs, total = JobRepository(session).list(
        JobFilters(status=JobStatus.QUEUED), limit=10, offset=0
    )
    assert (len(jobs), total) == (2, 2)
    assert {j.status for j in jobs} == {JobStatus.QUEUED}


def test_filter_by_job_type(session: Session) -> None:
    seed(session, 3, job_type="etl")
    seed(session, 4, job_type="report")
    jobs, total = JobRepository(session).list(
        JobFilters(job_type=JobType.REPORT), limit=2, offset=0
    )
    assert (len(jobs), total) == (2, 4)  # page size 2, total 4 matching


def test_filter_by_created_range_is_inclusive_start_exclusive_end(session: Session) -> None:
    seed(session, 10)  # minutes 0..9
    filters = JobFilters(
        created_after=BASE + timedelta(minutes=3), created_before=BASE + timedelta(minutes=6)
    )
    jobs, total = JobRepository(session).list(filters, limit=50, offset=0)
    assert total == 3
    assert [j.created_at for j in jobs] == [BASE + timedelta(minutes=m) for m in (5, 4, 3)]


def test_filters_combine_with_and(session: Session) -> None:
    seed(session, 4, job_type="etl", status="PENDING")
    seed(session, 4, job_type="report", status="PENDING")
    seed(session, 4, job_type="report", status="QUEUED")
    filters = JobFilters(status=JobStatus.PENDING, job_type=JobType.REPORT)
    jobs, total = JobRepository(session).list(filters, limit=50, offset=0)
    assert total == 4
    assert all(j.job_type == JobType.REPORT and j.status == JobStatus.PENDING for j in jobs)


def test_filter_matching_nothing(session: Session) -> None:
    seed(session, 3)
    assert JobRepository(session).list(
        JobFilters(status=JobStatus.DEAD_LETTER), limit=5, offset=0
    ) == ([], 0)


def test_get_and_get_by_idempotency_key(session: Session) -> None:
    job_id = insert_job(session, idempotency_key="k-1")
    session.commit()
    repo = JobRepository(session)
    assert repo.get(job_id) is not None
    assert repo.get(uuid.uuid4()) is None
    by_key = repo.get_by_idempotency_key("k-1")
    assert by_key is not None
    assert by_key.id == job_id
    assert repo.get_by_idempotency_key("missing") is None


def test_insert_if_absent_skips_duplicates_without_raising(session: Session) -> None:
    values = {
        "job_type": JobType.ETL, "payload": {}, "request_hash": "a" * 64,
        "max_attempts": 5, "idempotency_key": "dup",
    }  # fmt: skip
    repo = JobRepository(session)
    first = repo.insert_if_absent(values)
    second = repo.insert_if_absent(values)  # would be an IntegrityError without ON CONFLICT
    assert first is not None
    assert second is None
    session.commit()  # the transaction is still healthy


# ------------------------------------------------------ do the indexes help?
def explain(session: Session, sql: str) -> str:
    session.execute(text("SET LOCAL enable_seqscan = off"))  # force the planner to show index use
    return "\n".join(row[0] for row in session.execute(text(f"EXPLAIN {sql}")))


@pytest.mark.parametrize(
    ("sql", "index"),
    [
        ("SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT 20", "ix_jobs_created_at_id"),
        (
            "SELECT * FROM jobs WHERE status = 'RUNNING' "
            "ORDER BY created_at DESC, id DESC LIMIT 20",
            "ix_jobs_status_created_at_id",
        ),
        (
            "SELECT * FROM jobs WHERE job_type = 'report' "
            "ORDER BY created_at DESC, id DESC LIMIT 20",
            "ix_jobs_job_type_created_at_id",
        ),
        ("SELECT * FROM jobs WHERE idempotency_key = 'k'", "uq_jobs_idempotency_key"),
    ],
)
def test_list_and_lookup_queries_use_the_intended_index(
    session: Session, sql: str, index: str
) -> None:
    # Realistic mix: an index on a column only pays off when the filter is selective.
    seed(session, 190, job_type="etl", status="PENDING")
    seed(session, 5, job_type="report", status="QUEUED")
    seed(session, 5, job_type="api_call", status="RUNNING")
    session.execute(text("ANALYZE jobs"))
    plan = explain(session, sql)
    assert index in plan, plan


def test_attempt_history_query_uses_the_unique_index(session: Session) -> None:
    job_id = insert_job(session)
    for n in range(1, 4):
        insert_attempt(session, job_id, attempt_number=n, status="FAILED", error_type="E")
    session.execute(text("ANALYZE job_attempts"))
    plan = explain(
        session, f"SELECT * FROM job_attempts WHERE job_id = '{job_id}' ORDER BY attempt_number"
    )
    assert "uq_job_attempts_job_id_attempt_number" in plan, plan
