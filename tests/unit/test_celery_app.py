from rescueai.core.config import get_settings
from rescueai.worker.celery_app import QUEUE_NAME, VISIBILITY_TIMEOUT_SECONDS, celery_app


def test_broker_comes_from_settings_not_hardcoded() -> None:
    assert celery_app.conf.broker_url == get_settings().broker_url


def test_at_least_once_delivery_settings() -> None:
    conf = celery_app.conf
    assert conf.task_acks_late is True  # ack after completion => redelivery after a crash
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1


def test_postgres_is_source_of_truth_so_no_result_backend() -> None:
    assert celery_app.conf.task_ignore_result is True
    assert not celery_app.conf.result_backend


def test_safe_serialization_only() -> None:
    assert celery_app.conf.task_serializer == "json"
    assert list(celery_app.conf.accept_content) == ["json"]  # never unpickle broker messages


def test_queue_and_visibility_timeout() -> None:
    assert celery_app.conf.task_default_queue == QUEUE_NAME
    assert celery_app.conf.broker_transport_options["visibility_timeout"] == (
        VISIBILITY_TIMEOUT_SECONDS
    )


def test_no_tasks_registered_yet() -> None:
    user_tasks = [name for name in celery_app.tasks if not name.startswith("celery.")]
    assert user_tasks == []  # placeholder only; recovery/AI tasks are later phases
