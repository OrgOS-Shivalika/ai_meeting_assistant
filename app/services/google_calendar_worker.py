from datetime import datetime, timezone
import threading
from app.services.google_calendar_service import get_calendar_events
from app.db.database import SessionLocal
from app.db.models import Meeting, User
from app.pipelines.meeting_pipeline import MeetingPipeline
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
pipeline = MeetingPipeline()

def run_pipeline_async(meeting_id):
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if meeting:
            pipeline.run(db, meeting)
    except Exception as e:
        logger.error(f"Async pipeline failed for meeting {meeting_id}: {str(e)}")
    finally:
        db.close()

def process_calendar_events():
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.google_access_token.isnot(None)).all()
        logger.info(f"Checking calendar for {len(users)} users")

        for user in users:
            try:
                events = get_calendar_events(user)
                logger.info(f"Found {len(events)} events for user {user.email}")

                for event in events:
                    meet_link = event.get("hangoutLink")
                    event_id = event.get("id")
                    summary = event.get("summary", "Untitled Meeting")

                    if not event_id:
                        continue

                    # ⏰ check meeting start time (within auto-join window).
                    start_time = event["start"].get("dateTime")
                    if not start_time:
                        continue

                    start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    diff = (start_dt - now).total_seconds()
                    # Join if meeting starts in the next 2 minutes OR started in
                    # the last 5 minutes.
                    if not (-300 <= diff <= 120):
                        continue

                    existing = db.query(Meeting).filter_by(
                        google_event_id=event_id
                    ).first()

                    if existing:
                        # Pre-scheduled (e.g. created via the frontend schedule
                        # form). The worker still owns auto-join: when its
                        # start window arrives, transition pending → processing
                        # and dispatch the pipeline. Anything already further
                        # along (processing/completed/failed) is left alone.
                        if existing.status != "pending":
                            continue
                        join_url = existing.meeting_url or meet_link
                        if not join_url:
                            continue
                        logger.info(
                            f"🚀 Auto joining pre-scheduled meeting "
                            f"'{summary}' (id={existing.id}): {join_url}"
                        )
                        existing.meeting_url = join_url
                        existing.status = "processing"
                        # Refresh stored event data in case attendees / link
                        # changed since we created it.
                        existing.google_event_data = event
                        db.commit()

                        # Broadcast status update via WebSocket so UI transitions from 'Scheduled' to 'Processing'
                        try:
                            from app.api.ws_router import manager
                            import asyncio
                            # We use asyncio.run because this is usually called from a sync thread
                            asyncio.run(manager.broadcast(existing.id, {"type": "status_update", "status": "processing"}))
                        except Exception as ws_err:
                            logger.error(f"Failed to broadcast status update for meeting {existing.id}: {ws_err}")

                        # Use Celery if enabled, otherwise fall back to thread (local dev)
                        from app.config.settings import settings
                        if settings.USE_CELERY:
                            from app.celery_tasks.meeting_tasks import process_meeting
                            process_meeting.delay(existing.id)
                            logger.info(f"Dispatched pre-scheduled meeting {existing.id} to Celery")
                        else:
                            thread = threading.Thread(
                                target=run_pipeline_async, args=(existing.id,)
                            )
                            thread.start()
                        continue

                    # New event discovered on the calendar — create a Meeting
                    # row and dispatch.
                    if not meet_link:
                        continue

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

                    # Use Celery if enabled
                    if settings.USE_CELERY:
                        from app.celery_tasks.meeting_tasks import process_meeting
                        process_meeting.delay(meeting.id)
                        logger.info(f"Dispatched new auto-joined meeting {meeting.id} to Celery")
                    else:
                        thread = threading.Thread(
                            target=run_pipeline_async, args=(meeting.id,)
                        )
                        thread.start()
            except Exception as e:
                logger.error(f"Error processing calendar for user {user.email}: {str(e)}")

    except Exception as e:
        logger.error(f"Error in process_calendar_events: {str(e)}")
    finally:
        db.close()