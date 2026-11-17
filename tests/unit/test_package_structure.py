import importlib

import pytest

AGREED_PACKAGES = [
    "rescueai.api",
    "rescueai.api.v1",
    "rescueai.core",
    "rescueai.db",
    "rescueai.db.models",
    "rescueai.schemas",
    "rescueai.repositories",
    "rescueai.services",
    "rescueai.recovery",
    "rescueai.ai",
    "rescueai.jobs",
    "rescueai.jobs.handlers",
    "rescueai.worker",
    "rescueai.worker.celery_app",
]


@pytest.mark.parametrize("name", AGREED_PACKAGES)
def test_agreed_package_is_importable(name: str) -> None:
    assert importlib.import_module(name) is not None
