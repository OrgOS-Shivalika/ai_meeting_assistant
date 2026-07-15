import logging
import threading
from datetime import datetime, timedelta, timezone

from app.celery_app import celery
from app.db.database import SessionLocal
from app.db.models import Meeting, User
from app.utils.enums import MeetingStatus
from app.services.google_calendar_service import get_calendar_events
from app.pipelines.meeting_pipeline import MeetingPipeline

logger = logging.getLogger(__name__)

# Keep the local thread fallback for development without Celery
def run_pipeline_async(meeting_id):
    pipeline = MeetingPipeline()
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if meeting:
            pipeline.run(db, meeting)
    except Exception as e:
        logger.error(f"Async pipeline failed for meeting {meeting_id}: {str(e)}")
    finally:
        db.close()


@celery.task(name="meeting_ai.sync_google_calendar", bind=True)
def sync_google_calendar(self):
    """
    Celery Beat task to check Google Calendars and auto-join meetings.
    Moved from FastAPI's APScheduler to prevent blocking the web thread.
    """
    logger.info("📅 Celery: Starting Google Calendar Sync...")
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.google_access_token.isnot(None)).all()
        
        for user in users:
            try:
                events = get_calendar_events(user)
                if not events:
                    continue

                for event in events:
                    meet_link = event.get("hangoutLink")
                    event_id = event.get("id")
                    summary = event.get("summary", "Untitled Meeting")

                    if not event_id or not meet_link:
                        continue

                    start_time = event["start"].get("dateTime")
                    if not start_time:
                        continue

                    start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    diff = (start_dt - now).total_seconds()
                    
                    # Join window: Starts in < 2 mins OR Started < 5 mins ago
                    if not (-300 <= diff <= 120):
                        continue

                    # Dedup on TWO dimensions:
                    #  1. google_event_id — the calendar event ID
                    #  2. meeting_url within the last 10 min for this user
                    #     (catches the case where /inject-bot ran manually
                    #      seconds before we noticed the calendar event —
                    #      without this we'd send a second bot to the
                    #      same Meet URL).
                    recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
                    existing = (
                        db.query(Meeting)
                        .filter(
                            (Meeting.google_event_id == event_id)
                            | (
                                (Meeting.user_id == user.id)
                                & (Meeting.meeting_url == meet_link)
                                & (Meeting.created_at >= recent_cutoff)
                                & (Meeting.status.in_((MeetingStatus.PENDING, MeetingStatus.PROCESSING)))
                            )
                        )
                        .order_by(Meeting.created_at.desc())
                        .first()
                    )

                    if existing:
                        # If it was created by /inject-bot (no google_event_id),
                        # backfill it so future ticks don't recreate.
                        if not existing.google_event_id:
                            existing.google_event_id = event_id
                            existing.google_event_data = event
                            db.commit()
                            logger.info(
                                f"🔗 Linked existing meeting {existing.id} "
                                f"to calendar event {event_id} — skipping duplicate bot dispatch"
                            )
                            continue

                        # Pre-scheduled (from UI). Transition to processing.
                        if existing.status != "pending":
                            continue
                        
                        join_url = existing.meeting_url or meet_link
                        logger.info(f"🚀 Auto joining pre-scheduled meeting '{summary}' (id={existing.id}): {join_url}")
                        existing.meeting_url = join_url
                        existing.status = "processing"
                        existing.google_event_data = event
                        db.commit()

                        # Dispatch main pipeline task
                        from app.celery_tasks.meeting_tasks import process_meeting
                        process_meeting.delay(existing.id)
                        continue

                    # New event discovered on the calendar
                    logger.info(f"🚀 Auto joining meeting '{summary}': {meet_link}")

                    meeting = Meeting(
                        meeting_url=meet_link,
                        status="processing",
                        user_id=user.id,
                        organization_id=user.organization_id,
                        google_event_id=event_id,
                        google_event_data=event,
                        title=summary,
                    )
                    db.add(meeting)
                    db.commit()
                    db.refresh(meeting)

                    # Dispatch main pipeline task
                    from app.celery_tasks.meeting_tasks import process_meeting
                    process_meeting.delay(meeting.id)

            except Exception as e:
                logger.error(f"Error processing calendar for user {user.email}: {str(e)}")

    except Exception as e:
        logger.error(f"Error in sync_google_calendar: {str(e)}")
    finally:
        db.close()
