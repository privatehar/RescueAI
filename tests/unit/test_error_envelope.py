"""The error envelope: one shape everywhere, no echoed input, no leaked internals."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from rescueai.core.correlation import CORRELATION_HEADER
from rescueai.core.errors import ConflictError, NotFoundError
from rescueai.main import create_app


@pytest.fixture
def app() -> FastAPI:
    app = create_app()

    @app.get("/__boom")
    def boom() -> None:
        raise RuntimeError("connection string postgresql://u:hunter2@db/prod exploded")

    @app.get("/__db_down")
    def db_down() -> None:
        raise OperationalError("SELECT 1", {}, Exception("password=hunter2 refused"))

    @app.get("/__missing")
    def missing() -> None:
        raise NotFoundError("Widget 7 was not found.")

    @app.get("/__conflict")
    def conflict() -> None:
        raise ConflictError("Already exists.")

    return app


@pytest.fixture
def api(app: FastAPI) -> TestClient:
    # raise_server_exceptions=False: behave like a real server and return the 500 response.
    return TestClient(app, raise_server_exceptions=False)


def error_of(response_text: str) -> dict[str, object]:
    body = json.loads(response_text)
    assert list(body) == ["error"]  # exactly one top-level key
    error: dict[str, object] = body["error"]
    return error


def test_unknown_route_uses_the_envelope(api: TestClient) -> None:
    response = api.get("/nope", headers={CORRELATION_HEADER: "req-404"})
    error = error_of(response.text)
    assert response.status_code == 404
    assert error["code"] == "not_found"
    assert error["correlation_id"] == "req-404"


def test_method_not_allowed_uses_the_envelope(api: TestClient) -> None:
    response = api.post("/api/v1/health")
    assert response.status_code == 405
    assert error_of(response.text)["code"] == "method_not_allowed"
    assert "allow" in response.headers  # standard header preserved


def test_domain_errors_map_to_their_status_codes(api: TestClient) -> None:
    missing = api.get("/__missing")
    assert (missing.status_code, error_of(missing.text)["code"]) == (404, "not_found")
    conflict = api.get("/__conflict")
    assert (conflict.status_code, error_of(conflict.text)["code"]) == (409, "conflict")


def test_validation_error_lists_locations_but_never_echoes_input(api: TestClient) -> None:
    secret = "SUPER-SECRET-VALUE!"
    response = api.post(
        "/api/v1/jobs",
        json={"job_type": "etl", "payload": {"source_dataset": secret, "target_table": "t"}},
    )
    error = error_of(response.text)
    assert response.status_code == 422
    assert error["code"] == "validation_error"
    assert secret not in response.text  # pydantic's `input` must be stripped
    details = error["details"]
    assert isinstance(details, list)
    assert details[0]["loc"] == ["body", "etl", "payload", "source_dataset"]
    assert set(details[0]) == {"loc", "msg", "type"}


def test_malformed_json_is_a_422_envelope_without_echo(api: TestClient) -> None:
    response = api.post(
        "/api/v1/jobs",
        content='{"job_type": "etl", "token": "abc-secret"',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert error_of(response.text)["code"] == "validation_error"
    assert "abc-secret" not in response.text


def test_unhandled_exception_is_a_generic_500_with_correlation_id(api: TestClient) -> None:
    response = api.get("/__boom", headers={CORRELATION_HEADER: "req-500"})
    error = error_of(response.text)
    assert response.status_code == 500
    assert error["code"] == "internal_error"
    assert error["correlation_id"] == "req-500"
    assert response.headers[CORRELATION_HEADER] == "req-500"  # the gap noted in the last phase
    for leaked in ("hunter2", "postgresql://", "RuntimeError", "exploded", "Traceback"):
        assert leaked not in response.text


def test_database_outage_is_a_503_with_retry_after(api: TestClient) -> None:
    response = api.get("/__db_down")
    error = error_of(response.text)
    assert response.status_code == 503
    assert error["code"] == "service_unavailable"
    assert response.headers["retry-after"] == "5"
    assert "hunter2" not in response.text
    assert "password" not in response.text


def test_error_responses_always_carry_a_generated_correlation_id(api: TestClient) -> None:
    response = api.get("/__boom")
    cid = response.headers[CORRELATION_HEADER]
    assert len(cid) == 32
    assert error_of(response.text)["correlation_id"] == cid
