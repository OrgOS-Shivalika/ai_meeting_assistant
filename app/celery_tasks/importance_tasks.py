"""Phase 6A — importance scoring Celery wrapper.

Two entry points:

  - `score_org_task(organization_id)`  — Celery task; called from beat
    or one-off `process_id.delay(...)`.
  - `dispatch_score_org(organization_id)` — sync caller (used by the
    ingest path so a fresh chunk gets an immediate online score).

`dispatch_score_org` is fire-and-forget: it routes to Celery when
USE_CELERY=True, else runs inline. Never raises — a failed scorer
must not poison the ingest pipeline that called it.

Phase 6E adds the Celery beat schedule that calls `score_org_task`
hourly per active org. 6A only provides the task definition.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.celery_app import celery
from app.config.settings import settings
from app.db.database import SessionLocal
from app.services.importance import score_org
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@celery.task(name="meeting_ai.score_importance", bind=True)
def score_org_task(self, organization_id: str) -> dict:
    """Score all knowledge-tier rows in `organization_id`. Returns a
    summary dict mapping target_kind -> importance_run id."""
    logger.info("Celery task started: score_importance(org=%s)", organization_id)
    db = SessionLocal()
    try:
        result = score_org(db, organization_id=UUID(organization_id))
        return {"organization_id": organization_id,
                "runs": {k: str(v) for k, v in result.items()}}
    except Exception as e:
        logger.error("score_importance(%s) failed: %s", organization_id, e, exc_info=True)
        return {"organization_id": organization_id, "error": str(e)}
    finally:
        db.close()


def dispatch_score_org(organization_id: UUID | str) -> None:
    """Fire-and-forget importance scoring. Routes to Celery when
    configured, else runs inline. Never raises — caller must not be
    blocked by a scorer failure.
    """
    org_str = str(organization_id)
    try:
        if settings.USE_CELERY:
            score_org_task.delay(org_str)
            logger.info("importance: dispatched to Celery for org=%s", org_str)
            return
        # Inline path
        db = SessionLocal()
        try:
            score_org(db, organization_id=UUID(org_str))
        finally:
            db.close()
    except Exception as e:
        logger.error(
            "dispatch_score_org(%s) crashed: %s", org_str, e, exc_info=True,
        )


# ---------------------------------------------------------------------------
# Phase 6E — periodic fanout task
#
# Celery beat triggers `score_importance_all_orgs` on a schedule
# (configured in `app/celery_app.py`). The task itself iterates every
# active org and dispatches a per-org `score_org_task` so the work
# parallelizes across Celery workers.
# ---------------------------------------------------------------------------

@celery.task(name="meeting_ai.score_importance_all_orgs", bind=True)
def score_importance_all_orgs_task(self) -> dict:
    """Iterate active orgs and dispatch per-org scoring. Never raises;
    returns a count summary."""
    from app.db.models import Organization
    logger.info("Celery beat tick: score_importance_all_orgs")
    db = SessionLocal()
    dispatched = 0
    errors = 0
    try:
        org_ids = [r.id for r in db.execute(
            select(Organization.id)
        ).all()]
    finally:
        db.close()
    for oid in org_ids:
        try:
            score_org_task.delay(str(oid))
            dispatched += 1
        except Exception as e:
            errors += 1
            logger.error("score_all_orgs: failed to dispatch %s: %s", oid, e)
    logger.info(
        "score_importance_all_orgs: dispatched=%d errors=%d total_orgs=%d",
        dispatched, errors, len(org_ids),
    )
    return {"dispatched": dispatched, "errors": errors, "total_orgs": len(org_ids)}
