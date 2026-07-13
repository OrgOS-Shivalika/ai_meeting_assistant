"""Celery application factory.

The worker is started with:

    celery -A app.celery_app.celery worker --loglevel=info --pool=solo

The beat scheduler (Phase 6E) runs as a separate process:

    celery -A app.celery_app.celery beat --loglevel=info

`--pool=solo` is required on Windows for development. In Docker (Linux) the
default `prefork` pool is used.
"""

from celery import Celery
from celery.schedules import crontab

from app.config.settings import settings

# Force early init of the agents_v2 tracing shim so its ENABLED/DISABLED
# log line appears at worker startup — makes it obvious whether the
# Langfuse env vars actually reached this Python process. Without this,
# the module only initializes when the first agents_v2 task fires, and
# the diagnostic is easy to miss in log noise.
from app.agents_v2.shared import tracing as _agents_v2_tracing  # noqa: F401


celery = Celery(
    "meeting_ai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.celery_tasks.meeting_tasks",
        "app.celery_tasks.document_tasks",
        "app.celery_tasks.team_document_tasks",
        "app.celery_tasks.embedding_tasks",
        "app.celery_tasks.graph_tasks",
        "app.celery_tasks.document_graph_tasks",
        "app.celery_tasks.importance_tasks",
        "app.celery_tasks.consolidation_tasks",
        "app.celery_tasks.agent_tasks",
        "app.celery_tasks.calendar_tasks",
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

# ---------------------------------------------------------------------------
# Phase 6E — Celery beat schedule.
#
# Worker needs `celery beat` running alongside the worker to actually
# fire these. Cron values are intentionally off-peak: scoring at :07
# past every hour, consolidation Sundays at 03:30 UTC.
# ---------------------------------------------------------------------------
celery.conf.beat_schedule = {
    "score-importance-hourly": {
        "task": "meeting_ai.score_importance_all_orgs",
        "schedule": crontab(minute=7),  # every hour at H:07
    },
    "consolidate-memory-weekly": {
        "task": "meeting_ai.consolidate_memory_all_orgs",
        "schedule": crontab(minute=30, hour=3, day_of_week=0),
    },
    # Phase 7F — nightly rollup. Runs at 03:00 UTC so the data is
    # fresh for west-coast business hours the next morning. The task
    # aggregates *yesterday's* rag_query_runs across all orgs.
    "agent-performance-daily": {
        "task": "meeting_ai.aggregate_agent_performance_daily",
        "schedule": crontab(minute=0, hour=3),
    },
    "sync-google-calendar-frequent": {
        "task": "meeting_ai.sync_google_calendar",
        "schedule": crontab(minute="*/2"), # Every 2 minutes
    },
}
