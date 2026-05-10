"""Celery application factory.

The worker is started with:

    celery -A app.celery_app.celery worker --loglevel=info --pool=solo

`--pool=solo` is required on Windows for development. In Docker (Linux) the
default `prefork` pool is used.
"""

from celery import Celery

from app.config.settings import settings


celery = Celery(
    "meeting_ai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.celery_tasks.meeting_tasks",
        "app.celery_tasks.document_tasks",
        "app.celery_tasks.team_document_tasks",
    ],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Long-running tasks (transcript polling can take 20 minutes); make sure
    # the broker doesn't redeliver them prematurely.
    broker_transport_options={"visibility_timeout": 3600},
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # The meeting pipeline is idempotent only at coarse granularity (it
    # mutates the meeting row from "processing" -> "completed"). Don't retry
    # automatically; the route can resubmit if needed.
    task_default_retry_delay=0,
)
