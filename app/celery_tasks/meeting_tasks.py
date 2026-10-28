"""Celery tasks for meeting processing.

The pipeline previously ran inline via FastAPI BackgroundTasks. Pushing it onto
Celery means: (1) the API thread returns immediately even when the broker is
busy, (2) we can scale workers horizontally, (3) failures are visible in the
broker dashboard rather than swallowed in a closed FastAPI worker.
"""

from app.celery_app import celery
from app.db.database import SessionLocal
from app.db.models import Meeting
from app.pipelines.meeting_pipeline import MeetingPipeline
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@celery.task(name="meeting_ai.smoke", bind=True)
def smoke(self, payload: str = "ok") -> dict:
    """Round-trip test task — call from a script to prove broker connectivity."""
    return {"task_id": self.request.id, "payload": payload}


@celery.task(name="meeting_ai.process_meeting", bind=True)
def process_meeting(self, meeting_id: int) -> dict:
    """Run the full meeting pipeline (bot dispatch -> transcript -> AI analysis)
    in the background. Mirrors the in-process path in `routes.py` but runs
    inside the Celery worker so the API stays unblocked."""
    logger.info("Celery task started: process_meeting(meeting_id=%s)", meeting_id)
    pipeline = MeetingPipeline()

    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            logger.error("Meeting %s not found in worker", meeting_id)
            return {"status": "missing", "meeting_id": meeting_id}

        result = pipeline.run(db, meeting)
        return {"status": "completed", "meeting_id": meeting_id, "result": result}

    except Exception as exc:  # pipeline.run already marks meeting as failed
        logger.error("process_meeting(%s) failed: %s", meeting_id, exc)
        # Do not re-raise — pipeline.run handles state already; re-raising
        # would trigger Celery retry. Instead surface failure via return.
        return {"status": "failed", "meeting_id": meeting_id, "error": str(exc)}

    finally:
        db.close()


@celery.task(
    name="meeting_ai.export_meeting_to_drive",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    max_retries=3,
)
def export_meeting_to_drive(self, meeting_id: int, decisions=None, only_user_id=None) -> dict:
    """Write the meeting's transcript Doc to each recipient's Google Drive
    folder. Retries on transient Drive failures; the export is idempotent."""
    from app.services.drive_export_service import export_meeting

    db = SessionLocal()
    try:
        return export_meeting(db, meeting_id, decisions=decisions, only_user_id=only_user_id)
    finally:
        db.close()
