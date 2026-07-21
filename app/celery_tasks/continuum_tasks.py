"""Continuum Core — auto-process a completed meeting into its client board.

The meeting pipeline fans out here after a meeting completes. This task
answers one question — "does this meeting belong to a Continuum client?"
— and if yes, feeds the transcript into the Continuum agent (MODE A),
updating the client's persistent board + stage recommendation.

Routing rule (client = team): the meeting's team must be 1:1-linked to a
cc_clients row via cc_clients.team_id. The category name check is a
cheap pre-filter so non-Continuum meetings exit without a client query.

Design notes (same conventions as embedding_tasks):
- Best-effort: dispatch never raises into the meeting pipeline.
- Idempotent: a partial unique index on cc_runs(meeting_id) WHERE
  status='completed' makes double-processing impossible; we also check
  before calling the LLM to avoid wasting a run.
- Decoupled: failures land in a cc_runs row with status='failed',
  never touch meeting.status.
"""
from __future__ import annotations

from app.celery_app import celery
from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import Category, ContinuumClient, ContinuumRun, Meeting
from app.services.continuum import service
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _find_client_for_meeting(db, meeting: Meeting) -> ContinuumClient | None:
    """Meeting → Continuum client, or None if this isn't a Continuum meeting."""
    if not meeting.team_id or not meeting.category_id:
        return None
    category = db.query(Category).filter(Category.id == meeting.category_id).first()
    if not category or category.name != settings.CONTINUUM_CATEGORY_NAME:
        return None
    return (
        db.query(ContinuumClient)
        .filter(
            ContinuumClient.team_id == meeting.team_id,
            ContinuumClient.organization_id == meeting.organization_id,
        )
        .first()
    )


def _process_continuum_meeting_sync(db, meeting: Meeting) -> dict:
    client = _find_client_for_meeting(db, meeting)
    if client is None:
        return {"status": "skipped", "reason": "not a continuum meeting"}

    already = (
        db.query(ContinuumRun)
        .filter(
            ContinuumRun.meeting_id == meeting.id,
            ContinuumRun.status == "completed",
        )
        .first()
    )
    if already:
        return {"status": "skipped", "reason": "already processed"}

    transcript = (meeting.transcript_text or meeting.transcript or "").strip()
    if len(transcript.split()) < 10:
        logger.warning(
            "continuum: meeting %s has no usable transcript — skipping", meeting.id
        )
        return {"status": "skipped", "reason": "no transcript"}

    attendees = [p.name for p in (meeting.participants or []) if p.name]
    salesperson = ""
    if meeting.user is not None:
        salesperson = getattr(meeting.user, "email", "") or ""
    meeting_date = (meeting.ended_at or meeting.created_at)
    run = service.run_process(
        db,
        client,
        raw_input=transcript,
        attendees=attendees,
        salesperson=salesperson,
        meeting_date=meeting_date.date().isoformat() if meeting_date else None,
        meeting_id=meeting.id,
    )
    logger.info(
        "continuum: meeting %s processed into client %s (run %s, status %s, board v%s)",
        meeting.id, client.id, run.id, run.status, run.board_version_after,
    )
    return {"status": run.status, "run_id": run.id}


@celery.task(name="meeting_ai.process_continuum_meeting")
def process_continuum_meeting(meeting_id: int) -> dict:
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            logger.error("process_continuum_meeting: meeting %s not found", meeting_id)
            return {"status": "skipped", "reason": "meeting not found"}
        return _process_continuum_meeting_sync(db, meeting)
    finally:
        db.close()


def dispatch_continuum_process(meeting_id: int) -> None:
    """Single entry point used by the meeting pipeline. Never raises."""
    try:
        if settings.USE_CELERY:
            process_continuum_meeting.delay(meeting_id)
            logger.info("continuum dispatched to Celery for meeting %s", meeting_id)
            return
        db = SessionLocal()
        try:
            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            if not meeting:
                logger.error("dispatch_continuum_process: meeting %s not found", meeting_id)
                return
            _process_continuum_meeting_sync(db, meeting)
        finally:
            db.close()
    except Exception as exc:
        logger.error(
            "dispatch_continuum_process(%s) crashed: %s", meeting_id, exc, exc_info=True
        )
