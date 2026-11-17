import pytest
from pydantic import ValidationError

from rescueai.core.config import Settings

VALID_DB = "postgresql+psycopg://user:s3cret-pw@db:5432/app"
VALID_REDIS = "redis://redis:6379/0"


def make(**overrides: object) -> Settings:
    values: dict[str, object] = {"database_url": VALID_DB, "redis_url": VALID_REDIS}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_valid_settings_load_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest sets ENVIRONMENT=test for the suite; remove it to observe the real defaults.
    for name in ("ENVIRONMENT", "LOG_LEVEL", "LOG_JSON", "HEALTH_CHECK_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    settings = make()
    assert settings.environment == "local"
    assert settings.health_check_timeout_seconds == 2.0


def test_secrets_do_not_appear_in_repr_or_str() -> None:
    settings = make()
    assert "s3cret-pw" not in repr(settings)
    assert "s3cret-pw" not in str(settings)
    assert settings.database_url.get_secret_value() == VALID_DB


@pytest.mark.parametrize("url", ["postgresql://u:p@h/db", "mysql://u:p@h/db", "not-a-url"])
def test_database_url_must_use_psycopg_driver(url: str) -> None:
    with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
        make(database_url=url)


@pytest.mark.parametrize("url", ["http://h:6379", "localhost:6379"])
def test_redis_url_must_use_redis_scheme(url: str) -> None:
    with pytest.raises(ValidationError, match="redis"):
        make(redis_url=url)


def test_missing_required_settings_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("environment", "log_json", "expected"),
    [
        ("local", None, False),
        ("production", None, True),
        ("test", None, True),
        ("local", True, True),
        ("production", False, False),
    ],
)
def test_json_log_default_depends_on_environment(
    environment: str, log_json: bool | None, expected: bool
) -> None:
    assert make(environment=environment, log_json=log_json).use_json_logs is expected


def test_out_of_range_timeout_rejected() -> None:
    with pytest.raises(ValidationError):
        make(health_check_timeout_seconds=0)


def test_celery_broker_defaults_to_redis_url() -> None:
    assert make().broker_url == VALID_REDIS


def test_celery_broker_override_is_used_and_validated() -> None:
    assert make(celery_broker_url="redis://other:6379/1").broker_url == "redis://other:6379/1"
    with pytest.raises(ValidationError, match="redis"):
        make(celery_broker_url="amqp://guest@rabbit//")


def test_celery_broker_secret_not_in_repr() -> None:
    assert "pw123" not in repr(make(celery_broker_url="redis://:pw123@other:6379/1"))


def test_startup_defaults_fail_fast_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STARTUP_CHECK_ENABLED", raising=False)
    monkeypatch.delenv("STARTUP_MAX_WAIT_SECONDS", raising=False)
    settings = make()
    assert settings.startup_check_enabled is True
    assert settings.startup_max_wait_seconds == 30.0
