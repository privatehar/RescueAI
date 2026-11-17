from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from rescueai.schemas.job import JobCreate, JobCreateModel, JobListParams, request_fingerprint

ADAPTER: TypeAdapter[JobCreateModel] = TypeAdapter(JobCreate)

API = {"url": "https://api.example.com/v1/items", "method": "POST", "timeout_seconds": 5}
ETL = {"source_dataset": "orders_raw", "target_table": "orders_clean", "batch_size": 1000}
REPORT = {"report_type": "daily_summary", "period_days": 30, "output_format": "csv"}


def parse(job_type: str, payload: dict[str, Any], **extra: Any) -> JobCreateModel:
    return ADAPTER.validate_python({"job_type": job_type, "payload": payload, **extra})


def rejected(data: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as excinfo:
        ADAPTER.validate_python(data)
    return [e["type"] for e in excinfo.value.errors()]


@pytest.mark.parametrize(
    ("job_type", "payload"), [("api_call", API), ("etl", ETL), ("report", REPORT)]
)
def test_valid_job_of_each_type_is_accepted(job_type: str, payload: dict[str, Any]) -> None:
    assert parse(job_type, payload).job_type == job_type


def test_defaults_are_filled_in() -> None:
    etl = parse("etl", {"source_dataset": "a", "target_table": "b"})
    assert etl.payload.model_dump()["batch_size"] == 500
    call = parse("api_call", {"url": "http://example.com"})
    assert call.payload.model_dump() == {
        "url": "http://example.com",
        "method": "GET",
        "timeout_seconds": 10.0,
    }


def test_unknown_job_type_is_rejected() -> None:
    assert rejected({"job_type": "shell", "payload": {}}) == ["union_tag_invalid"]


def test_missing_job_type_or_payload_is_rejected() -> None:
    assert rejected({"payload": ETL}) == ["union_tag_not_found"]
    assert "missing" in rejected({"job_type": "etl"})


def test_payload_of_another_job_type_is_rejected() -> None:
    types = rejected({"job_type": "etl", "payload": REPORT})
    assert "extra_forbidden" in types
    assert "missing" in types


def test_unknown_top_level_field_is_rejected() -> None:
    assert "extra_forbidden" in rejected({"job_type": "etl", "payload": ETL, "priority": 9})


def test_unknown_payload_field_is_rejected() -> None:
    assert "extra_forbidden" in rejected({"job_type": "etl", "payload": {**ETL, "shell": "rm -rf"}})


@pytest.mark.parametrize(
    "bad",
    [
        {**ETL, "batch_size": "500"},  # string for an int
        {**ETL, "batch_size": True},  # bool is not an int
        {**ETL, "batch_size": 5.5},
        {**ETL, "batch_size": 0},
        {**ETL, "batch_size": 10_001},
        {**ETL, "source_dataset": "Orders"},  # uppercase
        {**ETL, "source_dataset": "has-hyphen"},
        {**ETL, "target_table": "a" * 65},
        {**ETL, "target_table": ""},
    ],
)
def test_invalid_etl_payloads_are_rejected(bad: dict[str, Any]) -> None:
    rejected({"job_type": "etl", "payload": bad})


@pytest.mark.parametrize(
    "bad",
    [
        {**API, "url": "ftp://example.com/file"},
        {**API, "url": "not a url"},
        {**API, "url": "//example.com"},
        {**API, "url": ""},
        {**API, "url": "https://user:secret@example.com/"},  # credentials must not be embedded
        {**API, "url": "https://example.com/" + "a" * 2048},
        {**API, "method": "TRACE"},
        {**API, "method": "get"},
        {**API, "timeout_seconds": 0},
        {**API, "timeout_seconds": 61},
        {**API, "timeout_seconds": "5"},
    ],
)
def test_invalid_api_call_payloads_are_rejected(bad: dict[str, Any]) -> None:
    rejected({"job_type": "api_call", "payload": bad})


@pytest.mark.parametrize(
    "bad",
    [
        {**REPORT, "report_type": "everything"},
        {**REPORT, "period_days": 0},
        {**REPORT, "period_days": 366},
        {**REPORT, "output_format": "pdf"},
    ],
)
def test_invalid_report_payloads_are_rejected(bad: dict[str, Any]) -> None:
    rejected({"job_type": "report", "payload": bad})


def test_int_is_accepted_where_float_is_expected() -> None:
    call = parse("api_call", {"url": "https://example.com", "timeout_seconds": 5})
    assert call.payload.timeout_seconds == 5.0  # type: ignore[union-attr]


@pytest.mark.parametrize("key", ["order-123", "a.b_c:d-9", "A" * 128, "x"])
def test_valid_idempotency_keys(key: str) -> None:
    assert parse("etl", ETL, idempotency_key=key).idempotency_key == key


@pytest.mark.parametrize("key", ["", "has space", "semi;colon", "a" * 129, "naïve", "tab\t", 123])
def test_invalid_idempotency_keys(key: Any) -> None:
    rejected({"job_type": "etl", "payload": ETL, "idempotency_key": key})


@pytest.mark.parametrize("value", [0, 11, -1, True, "5", 2.5])
def test_invalid_max_attempts(value: Any) -> None:
    rejected({"job_type": "etl", "payload": ETL, "max_attempts": value})


@pytest.mark.parametrize("value", [1, 5, 10])
def test_valid_max_attempts(value: int) -> None:
    assert parse("etl", ETL, max_attempts=value).max_attempts == value


# ------------------------------------------------------------- fingerprinting
def test_fingerprint_is_a_64_char_hex_digest() -> None:
    _, digest = request_fingerprint(parse("etl", ETL))
    assert len(digest) == 64
    assert int(digest, 16) >= 0


def test_fingerprint_ignores_key_order() -> None:
    a = parse("etl", {"source_dataset": "a", "target_table": "b", "batch_size": 5})
    b = parse("etl", {"batch_size": 5, "target_table": "b", "source_dataset": "a"})
    assert request_fingerprint(a) == request_fingerprint(b)


def test_fingerprint_treats_explicit_default_like_omitted() -> None:
    omitted = parse("etl", {"source_dataset": "a", "target_table": "b"})
    explicit = parse("etl", {"source_dataset": "a", "target_table": "b", "batch_size": 500})
    assert request_fingerprint(omitted) == request_fingerprint(explicit)


def test_fingerprint_changes_with_payload_type_and_max_attempts() -> None:
    base = request_fingerprint(parse("etl", ETL))[1]
    assert request_fingerprint(parse("etl", {**ETL, "batch_size": 1}))[1] != base
    assert request_fingerprint(parse("etl", ETL, max_attempts=3))[1] != base
    assert request_fingerprint(parse("etl", ETL, idempotency_key="k"))[1] == base  # key not hashed


def test_fingerprint_payload_is_json_serializable() -> None:
    payload, _ = request_fingerprint(parse("api_call", API))
    assert payload == {"url": API["url"], "method": "POST", "timeout_seconds": 5.0}


# ------------------------------------------------------------ list parameters
def test_list_params_defaults() -> None:
    params = JobListParams()
    assert (params.limit, params.offset, params.status) == (20, 0, None)


@pytest.mark.parametrize(
    "kwargs", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "BOGUS"}]
)
def test_list_params_reject_bad_values(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        JobListParams(**kwargs)


def test_list_params_require_timezone_aware_datetimes() -> None:
    with pytest.raises(ValidationError):
        JobListParams(created_after=datetime(2026, 1, 1))  # naive
    assert JobListParams(created_after=datetime(2026, 1, 1, tzinfo=UTC)).created_after


def test_list_params_reject_inverted_or_empty_range() -> None:
    early, late = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        JobListParams(created_after=late, created_before=early)
    with pytest.raises(ValidationError):
        JobListParams(created_after=early, created_before=early)


def test_list_params_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        JobListParams(sort="id")  # type: ignore[call-arg]
