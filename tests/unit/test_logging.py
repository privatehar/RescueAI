import json

import pytest

from rescueai.core.logging import REDACTED, configure_logging, get_logger, redact_sensitive_keys


def _last_json_line(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    parsed: dict[str, object] = json.loads(lines[-1])
    return parsed


def test_json_logging_emits_structured_record(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_logs=True)
    get_logger("test").info("something_happened", job_id="abc", attempt=2)

    record = _last_json_line(capsys)
    assert record["event"] == "something_happened"
    assert record["job_id"] == "abc"
    assert record["attempt"] == 2
    assert record["level"] == "info"
    assert "timestamp" in record


def test_level_filters_lower_severity(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="WARNING", json_logs=True)
    get_logger("test").info("too_quiet")
    assert capsys.readouterr().out == ""


def test_sensitive_keys_are_redacted_in_output(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_logs=True)
    get_logger("test").info(
        "login",
        password="hunter2",
        openai_api_key="sk-xyz",
        user="alice",
        headers={"Authorization": "Bearer abc", "accept": "json"},
    )
    out = capsys.readouterr().out
    assert "hunter2" not in out
    assert "sk-xyz" not in out
    assert "Bearer abc" not in out
    record = json.loads(out.splitlines()[-1])
    assert record["user"] == "alice"
    assert record["headers"]["accept"] == "json"


def test_stdlib_logging_goes_through_same_pipeline(capsys: pytest.CaptureFixture[str]) -> None:
    import logging

    configure_logging(level="INFO", json_logs=True)
    logging.getLogger("some.library").warning("from stdlib")
    record = _last_json_line(capsys)
    assert record["event"] == "from stdlib"
    assert record["level"] == "warning"


@pytest.mark.parametrize(
    ("key", "redacted"),
    [
        ("password", True),
        ("DB_PASSWORD", True),
        ("api_key", True),
        ("OPENAI_API_KEY", True),
        ("client_secret", True),
        ("access_token", True),
        ("token", True),
        ("Authorization", True),
        ("cookie", True),
        # Must NOT be redacted: useful, non-secret fields (token *counts* matter for AI cost).
        ("max_tokens", False),
        ("prompt_tokens", False),
        ("job_id", False),
        ("path", False),
    ],
)
def test_redaction_key_matching(key: str, redacted: bool) -> None:
    result = redact_sensitive_keys(None, "info", {key: "value"})
    assert (result[key] == REDACTED) is redacted
