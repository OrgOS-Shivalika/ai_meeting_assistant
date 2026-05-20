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
        # Phase 4D — registers `meeting_ai.extract_document_graph`. Without
        # this entry the worker logs "Received unregistered task of type
        # 'meeting_ai.extract_document_graph'" and silently drops the
        # message, leaving every doc stuck at graph_status='pending'.
        "app.celery_tasks.document_graph_tasks",
        # Phase 6A — registers `meeting_ai.score_importance`. Same
        # "must be in include OR worker drops the message" rule.
        "app.celery_tasks.importance_tasks",
        # Phase 6D — registers `meeting_ai.consolidate_memory`.
        "app.celery_tasks.consolidation_tasks",
        # Phase 7F — registers `meeting_ai.aggregate_agent_performance_daily`
        # and `meeting_ai.aggregate_agent_performance_for_date`.
        "app.celery_tasks.agent_tasks",
        # Phase 8D template_tasks (upgrade detector) removed in Phase 8F
        # cleanup — the new sparse-override model has no equivalent of
        # the 3-way-diff upgrade proposal flow.
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
}
