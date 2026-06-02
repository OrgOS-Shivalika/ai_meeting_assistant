import logging
from typing import Dict, Any
from app.db.database import SessionLocal
from app.db.models import Task
from app.services.live_events.event_models import LiveCognitiveEvent
from datetime import datetime

logger = logging.getLogger(__name__)

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

                if existing:
                    # Update
                    existing.owner_name = payload.get("owner")
                    existing.due_date = cls._parse_date(payload.get("deadline"))
                    existing.is_completed = 1 if payload.get("status") == "completed" else 0
                    logger.debug(f"Updated existing task {existing.id} in DB")
                else:
                    # Create new
                    new_task = Task(
                        meeting_id=meeting_id,
                        task=task_text,
                        owner_name=payload.get("owner"),
                        due_date=cls._parse_date(payload.get("deadline")),
                        is_completed=0
                    )
                    db.add(new_task)
                    logger.debug(f"Inserted new live task into DB")
                
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
        if not date_str:
            return None
        try:
            # Basic parser for common formats
            if isinstance(date_str, str):
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return None
        except Exception:
            return None
