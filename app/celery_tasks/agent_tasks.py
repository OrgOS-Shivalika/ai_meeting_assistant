"""Phase 7F — analytics rollup Celery task.

Two entry points:

  - `aggregate_agent_performance_daily()` — beat-scheduled (03:00 UTC).
    Aggregates *yesterday's* `rag_query_runs` rows into
    `agent_performance_daily`. Idempotent re-run via the analytics
    service's DELETE-then-INSERT pattern.

  - `aggregate_agent_performance_for_date(bucket_date_iso)` — manual
    one-off for backfills or recomputing after a fix. Accepts an ISO
    date string ('YYYY-MM-DD').

Both wrap the analytics-service entry points and handle the
session lifecycle. Failures log + return — they never propagate to
the broker, so a poison-pill day doesn't stall the queue.
"""
from __future__ import annotations

from datetime import date

from app.celery_app import celery
from app.db.database import SessionLocal
from app.services.agents.analytics import (
    rebuild_daily_bucket, rebuild_yesterday_all_orgs,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@celery.task(name="meeting_ai.aggregate_agent_performance_daily", bind=True)
def aggregate_agent_performance_daily(self) -> dict:
    """Aggregate yesterday's rag_query_runs across all orgs into the
    daily rollup table. Returns a summary dict."""
    logger.info("Celery task started: aggregate_agent_performance_daily")
    db = SessionLocal()
    try:
        n = rebuild_yesterday_all_orgs(db)
        return {"status": "ok", "rows_inserted": n}
    except Exception as e:
        logger.error(
            "aggregate_agent_performance_daily failed: %s", e, exc_info=True,
        )
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()


@celery.task(
    name="meeting_ai.aggregate_agent_performance_for_date", bind=True,
)
def aggregate_agent_performance_for_date(self, bucket_date_iso: str) -> dict:
    """Aggregate a specific calendar day (ISO 'YYYY-MM-DD'). Useful
    for backfilling historical data or recomputing after a bugfix."""
    logger.info(
        "Celery task started: aggregate_agent_performance_for_date(%s)",
        bucket_date_iso,
    )
    db = SessionLocal()
    try:
        bucket = date.fromisoformat(bucket_date_iso)
        n = rebuild_daily_bucket(db, bucket_date=bucket)
        return {"status": "ok", "bucket_date": bucket_date_iso, "rows_inserted": n}
    except Exception as e:
        logger.error(
            "aggregate_agent_performance_for_date(%s) failed: %s",
            bucket_date_iso, e, exc_info=True,
        )
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()
