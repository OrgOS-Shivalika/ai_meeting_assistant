"""Phase 6D — consolidation Celery task.

Single task that runs both passes (archive + merge suggestions) for
one org. Phase 6E adds the Celery beat schedule that calls this
weekly per active org. 6D only provides the task itself.
"""
from __future__ import annotations

from uuid import UUID

from app.celery_app import celery
from app.config.settings import settings
from app.db.database import SessionLocal
from app.services.consolidation import run_archive, run_merge_suggestions
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@celery.task(name="meeting_ai.consolidate_memory", bind=True)
def consolidate_memory_task(self, organization_id: str) -> dict:
    """Run both consolidation passes for `organization_id`. Returns a
    summary dict with archive counts + suggestion count."""
    logger.info("Celery task started: consolidate_memory(org=%s)", organization_id)
    db = SessionLocal()
    try:
        archive_counts = run_archive(db, organization_id=UUID(organization_id))
        suggestions_written = run_merge_suggestions(
            db, organization_id=UUID(organization_id),
        )
        return {
            "organization_id": organization_id,
            "archived": archive_counts,
            "merge_suggestions_written": suggestions_written,
        }
    except Exception as e:
        logger.error(
            "consolidate_memory(%s) failed: %s",
            organization_id, e, exc_info=True,
        )
        return {"organization_id": organization_id, "error": str(e)}
    finally:
        db.close()


def dispatch_consolidate_memory(organization_id: UUID | str) -> None:
    """Route to Celery or inline. Never raises."""
    org_str = str(organization_id)
    try:
        if settings.USE_CELERY:
            consolidate_memory_task.delay(org_str)
            logger.info("consolidation: dispatched to Celery for org=%s", org_str)
            return
        db = SessionLocal()
        try:
            run_archive(db, organization_id=UUID(org_str))
            run_merge_suggestions(db, organization_id=UUID(org_str))
        finally:
            db.close()
    except Exception as e:
        logger.error(
            "dispatch_consolidate_memory(%s) crashed: %s",
            org_str, e, exc_info=True,
        )


# ---------------------------------------------------------------------------
# Phase 6E — periodic fanout task (sibling of score_importance_all_orgs)
# ---------------------------------------------------------------------------

@celery.task(name="meeting_ai.consolidate_memory_all_orgs", bind=True)
def consolidate_memory_all_orgs_task(self) -> dict:
    """Iterate active orgs and dispatch per-org consolidation. Beat
    triggers this weekly. Never raises."""
    from sqlalchemy import select
    from app.db.models import Organization
    logger.info("Celery beat tick: consolidate_memory_all_orgs")
    db = SessionLocal()
    dispatched = 0
    errors = 0
    try:
        org_ids = [r.id for r in db.execute(select(Organization.id)).all()]
    finally:
        db.close()
    for oid in org_ids:
        try:
            consolidate_memory_task.delay(str(oid))
            dispatched += 1
        except Exception as e:
            errors += 1
            logger.error("consolidate_all_orgs: failed to dispatch %s: %s", oid, e)
    logger.info(
        "consolidate_memory_all_orgs: dispatched=%d errors=%d total_orgs=%d",
        dispatched, errors, len(org_ids),
    )
    return {"dispatched": dispatched, "errors": errors, "total_orgs": len(org_ids)}
