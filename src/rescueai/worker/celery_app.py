"""Celery application: configuration placeholder (no tasks yet).

Run a worker (once tasks exist):  celery -A rescueai.worker.celery_app:celery_app worker

Design choices that matter for reliability (explained in the architecture notes):

* ``task_acks_late`` + ``task_reject_on_worker_lost``: a message is acknowledged only AFTER the
  task finishes, so if a worker dies mid-task the broker redelivers it. That gives
  *at-least-once delivery*, NOT exactly-once execution. Handlers and the DB claim logic must
  therefore be idempotent (later phases).
* ``worker_prefetch_multiplier=1``: a worker takes one task at a time, so one slow job cannot
  hide queued jobs behind it and a crash strands at most one message.
* No result backend and ``task_ignore_result``: PostgreSQL is the durable source of truth for job
  state and history. Redis only carries messages.
* ``visibility_timeout`` (Redis transport): if a task is not acked within this window Redis
  redelivers it, so it MUST exceed the longest task runtime or running jobs get duplicated.
"""

from celery import Celery

from rescueai.core.config import get_settings

QUEUE_NAME = "rescueai"
# Placeholder: must be revisited together with task time limits when jobs are implemented.
VISIBILITY_TIMEOUT_SECONDS = 3600


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery("rescueai", broker=settings.broker_url, include=[])
    app.conf.update(
        task_default_queue=QUEUE_NAME,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_ignore_result=True,
        task_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # Keep retrying the broker connection at worker start (e.g. Redis still booting).
        broker_connection_retry_on_startup=True,
        broker_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT_SECONDS},
    )
    return app


# Module-level instance because the Celery CLI needs an importable app object.
celery_app = create_celery_app()
