"""Application settings, loaded from environment variables (and an optional .env file).

Secrets (connection strings) are ``SecretStr`` so they never appear in ``repr()`` or logs.
Missing required settings make the app fail fast at startup instead of at first use.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["local", "test", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # None => human-readable console logs locally, JSON everywhere else.
    log_json: bool | None = None

    database_url: SecretStr
    redis_url: SecretStr

    # Celery broker. Defaults to REDIS_URL; override only to use a different Redis DB/instance.
    celery_broker_url: SecretStr | None = None

    # Startup behaviour: wait (with backoff) for PostgreSQL and Redis, then FAIL FAST with a clear
    # error instead of serving a broken app. The container orchestrator then restarts us.
    startup_check_enabled: bool = True
    startup_max_wait_seconds: float = Field(default=30.0, ge=0, le=600)

    # Default retry budget for new jobs (a request may override it within 1..10).
    default_max_attempts: int = Field(default=5, ge=1, le=10)

    # Upper bound for each dependency probe in /health, so a hung dependency
    # cannot hang the health endpoint (and any orchestrator probing it).
    health_check_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=100)

    @field_validator("database_url")
    @classmethod
    def _require_psycopg_driver(cls, value: SecretStr) -> SecretStr:
        # A bare "postgresql://" makes SQLAlchemy look for psycopg2, which we don't install.
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must start with 'postgresql+psycopg://'")
        return value

    @field_validator("redis_url", "celery_broker_url")
    @classmethod
    def _require_redis_scheme(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith(("redis://", "rediss://")):
            raise ValueError("Redis URLs must start with 'redis://' or 'rediss://'")
        return value

    @property
    def broker_url(self) -> str:
        """Celery broker URL (the explicit override, otherwise REDIS_URL)."""
        return (self.celery_broker_url or self.redis_url).get_secret_value()

    @property
    def use_json_logs(self) -> bool:
        if self.log_json is not None:
            return self.log_json
        return self.environment != "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required fields are read from the environment
