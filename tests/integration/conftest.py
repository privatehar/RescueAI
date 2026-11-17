"""Fixtures for tests against a REAL PostgreSQL server (run with: pytest -m integration).

Strategy: create a throw-away database, apply the real Alembic migration to it (so the migration
itself is exercised on every run), truncate tables between tests, drop the database at the end.
The role in DATABASE_URL needs the CREATEDB privilege (it is a superuser in the Compose setup).
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from rescueai.core.config import get_settings
from rescueai.db.session import dispose_engine, get_sessionmaker
from rescueai.main import create_app

ROOT = Path(__file__).resolve().parents[2]
ALL_TABLES = "audit_events, recovery_actions, failure_analyses, job_attempts, outbox_events, jobs"


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # ConfigParser escaping
    return config


def _admin_engine(url: str) -> Engine:
    return create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")


def create_database(server_url: str) -> str:
    name = f"rescueai_test_{uuid.uuid4().hex[:10]}"
    admin = _admin_engine(server_url)
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return make_url(server_url).set(database=name).render_as_string(hide_password=False)


def drop_database(url: str) -> None:
    name = make_url(url).database
    admin = _admin_engine(url)
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def server_url() -> str:
    return os.environ["DATABASE_URL"]  # captured once, before any test redirects the app


@pytest.fixture(scope="session")
def migrated_db_url(server_url: str) -> Iterator[str]:
    url = create_database(server_url)
    command.upgrade(alembic_config(url), "head")
    yield url
    drop_database(url)


@pytest.fixture
def fresh_db_url(server_url: str) -> Iterator[str]:
    """An EMPTY database (no tables), for migration tests."""
    url = create_database(server_url)
    yield url
    drop_database(url)


@pytest.fixture
def app_db(migrated_db_url: str) -> Iterator[str]:
    """Point the application at the migrated test database and clean it after the test."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = migrated_db_url
    get_settings.cache_clear()
    dispose_engine()
    yield migrated_db_url
    dispose_engine()
    engine = create_engine(migrated_db_url)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {ALL_TABLES} RESTART IDENTITY CASCADE"))
    engine.dispose()
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous
    get_settings.cache_clear()


@pytest.fixture
def session(app_db: str) -> Iterator[Session]:
    with get_sessionmaker()() as db_session:
        yield db_session
        db_session.rollback()


@pytest.fixture
def api_client(app_db: str) -> Iterator[TestClient]:
    with TestClient(create_app()) as client:
        yield client
