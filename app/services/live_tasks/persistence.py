import logging
import re
from typing import Dict, Any
from app.db.database import SessionLocal
from app.db.models import Meeting, Task
from app.services.kanban.defaults import resolve_landing_for_meeting
from app.services.kanban.positions import position_for_end
from app.services.live_events.event_models import LiveCognitiveEvent
from datetime import datetime

logger = logging.getLogger(__name__)

# Phase 13D revised — only ISO-shaped strings are persisted into
# `tasks.due_date`. Natural-language phrases like "by Friday" stay in
# `LiveTask.deadline` for display but never reach the date column.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?.*)?$")

class LiveTaskPersistence:
    """
    Handles real-time persistence of detected tasks to the database.
    This ensures that live tasks are not lost if the UI is refreshed.
    """

    @classmethod
    def handle_event(cls, event: LiveCognitiveEvent) -> None:
        """Subscriber callback for LiveEventBus."""
        if event.event_type not in ["task.created", "task.updated"]:
            return

        logger.info(f"💾 LiveTaskPersistence: Saving task '{event.event_type}' for meeting {event.meeting_id}")
        
        try:
            meeting_id = int(event.meeting_id)
            payload = event.payload
            
            # Map LiveTask payload to Database Task model
            # Note: We use the 'id' (UUID) from the live engine to track the same task
            live_id = payload.get("id")
            task_text = payload.get("task")
            
            if not task_text or not live_id:
                return

            db = SessionLocal()
            try:
                # 1. Look for existing task by live_id (stored in a metadata field or similar)
                # Since the current Task model doesn't have a 'live_id' column, we'll match by text
                # and meeting_id for now, OR we could add a live_id column.
                # Let's match by task text + meeting_id as a fallback.
                existing = db.query(Task).filter(
                    Task.meeting_id == meeting_id,
                    Task.task == task_text
                ).first()

                # Phase 13D revised — prefer the LLM's ISO `due_date`.
                # `deadline` is the speaker's natural phrasing ("by
                # Friday") and is NOT parseable as a date here — we keep
                # it on the live event for display only. If the LLM
                # didn't resolve a concrete date, `due_date` stays None
                # in the DB; that's a valid, tracked dateless task.
                resolved_due_date = cls._parse_date(payload.get("due_date"))

                if existing:
                    # Update
                    existing.owner_name = payload.get("owner")
                    existing.due_date = resolved_due_date
                    # Keep status + is_completed in lockstep — the K1
                    # CHECK constraint enforces this; bypassing it
                    # raises IntegrityError. `status='done'` is the
                    # single source of truth.
                    completed = payload.get("status") == "completed"
                    existing.is_completed = 1 if completed else 0
                    existing.status = "done" if completed else (existing.status or "todo")
                    logger.debug(f"Updated existing task {existing.id} in DB")
                else:
                    # Phase 14 — attach the new task to the org's
                    # default board's "To Do" column so it shows up on
                    # the Kanban surface immediately. We look up the
                    # meeting to get its organization_id; if the
                    # meeting somehow doesn't exist yet (race), we
                    # insert without board info — the K2 reconciler
                    # will fix it later.
                    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
                    board_id, column_id = (None, None)
                    position = None
                    if meeting is not None:
                        board_id, column_id = resolve_landing_for_meeting(
                            db, meeting.organization_id, status="todo",
                        )
                        if column_id is not None:
                            position = position_for_end(db, column_id)

                    new_task = Task(
                        meeting_id=meeting_id,
                        task=task_text,
                        owner_name=payload.get("owner"),
                        due_date=resolved_due_date,
                        is_completed=0,
                        status="todo",
                        board_id=board_id,
                        column_id=column_id,
                        position=position,
                    )
                    db.add(new_task)
                    logger.debug(
                        "Inserted new live task into DB (board=%s, column=%s, pos=%s)",
                        board_id, column_id, position,
                    )
                
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to persist live task to DB: {e}")
            finally:
                db.close()
                
        except ValueError:
            logger.error(f"LiveTaskPersistence: Invalid meeting_id {event.meeting_id}")
        except Exception as e:
            logger.error(f"LiveTaskPersistence: Unexpected error: {e}")

    @staticmethod
    def _parse_date(date_str: Any) -> Any:
        """Convert an ISO-shaped string into a datetime. Returns None for
        anything non-ISO (e.g. "by Friday") so dateless tasks land cleanly
        as NULL rather than failing the row insert.
        """
        if not date_str or not isinstance(date_str, str):
            return None
        s = date_str.strip()
        if not _ISO_DATE_RE.match(s):
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
