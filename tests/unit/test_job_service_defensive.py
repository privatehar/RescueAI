"""Rare paths in the create-job transaction logic, exercised with a stubbed repository."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import TypeAdapter

from rescueai.repositories.jobs import JobRepository
from rescueai.schemas.job import JobCreate, JobCreateModel
from rescueai.services.job_service import create_job

ADAPTER: TypeAdapter[JobCreateModel] = TypeAdapter(JobCreate)
BODY: dict[str, Any] = {
    "job_type": "etl",
    "payload": {"source_dataset": "a", "target_table": "b"},
}


def run(**overrides: Any) -> MagicMock:
    session = MagicMock()
    try:
        create_job(
            session,
            ADAPTER.validate_python({**BODY, **overrides}),
            correlation_id=None,
            default_max_attempts=5,
        )
    finally:
        run.session = session  # type: ignore[attr-defined]
    return session


def test_gives_up_after_a_bounded_number_of_passes_when_the_conflicting_row_keeps_vanishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserts: list[int] = []

    def skipped(_self: Any, _values: Any) -> None:
        inserts.append(1)

    monkeypatch.setattr(JobRepository, "insert_if_absent", skipped)
    monkeypatch.setattr(JobRepository, "get_by_idempotency_key", lambda _s, _k: None)

    with pytest.raises(RuntimeError, match="could not resolve"):
        run(idempotency_key="vanishing")
    assert len(inserts) == 3  # bounded: never loops forever
    run.session.rollback.assert_called()  # type: ignore[attr-defined]


def test_a_skipped_insert_without_an_idempotency_key_is_reported_as_a_bug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(JobRepository, "insert_if_absent", lambda _s, _v: None)
    with pytest.raises(RuntimeError, match="without an idempotency key"):
        run()  # no key: nothing can legitimately conflict
