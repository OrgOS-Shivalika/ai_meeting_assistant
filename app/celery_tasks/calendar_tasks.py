import logging
import threading
from datetime import datetime, timezone

from app.celery_app import celery
from app.db.database import SessionLocal
from app.db.models import Meeting, User
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

                    existing = db.query(Meeting).filter_by(google_event_id=event_id).first()

                    if existing:
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
