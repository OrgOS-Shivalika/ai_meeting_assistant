import logging
import asyncio
from typing import List, Callable, Dict
from app.services.live_events.event_models import LiveCognitiveEvent

logger = logging.getLogger(__name__)

class LiveEventBus:
    """Singleton bus for real-time cognitive events."""
    
    def __init__(self):
        self._subscribers: List[Callable] = []

    def subscribe(self, callback: Callable[[LiveCognitiveEvent], None]) -> None:
        self._subscribers.append(callback)

    def emit(self, event: LiveCognitiveEvent) -> None:
        """Dispatches an event to all subscribers."""
        logger.info(f"📢 LiveEventBus: Emitting '{event.event_type}' for meeting {event.meeting_id}")
        
        # 1. Internal callbacks
        for sub in self._subscribers:
            try:
                sub(event)
            except Exception as e:
                logger.error(f"LiveEventBus: Subscriber error: {e}")
                
        # 2. WebSocket Broadcast (Placeholder for app/api/ws_router.py integration)
        self._broadcast_to_ui(event)

    def _broadcast_to_ui(self, event: LiveCognitiveEvent) -> None:
        """Signals the UI layer via WebSockets."""
        from app.api.ws_router import manager
        import asyncio
        import json

        logger.info(f"📢 LiveEventBus: Broadcasting '{event.event_type}' to UI for meeting {event.meeting_id}")
        
        try:
            m_id = int(event.meeting_id)
            payload = {
                "type": "cognitive_event",
                "event_type": event.event_type,
                "meeting_id": event.meeting_id,
                "timestamp": event.timestamp.isoformat(),
                "payload": event.payload,
                "confidence": event.confidence,
                "trace_id": event.trace_id
            }
            
            # Since LiveEventBus might be called from synchronous threads (like Celery or sync routes)
            # but manager.broadcast is an async method of ConnectionManager, we need to handle the loop correctly.
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(manager.broadcast(m_id, payload))
                else:
                    loop.run_until_complete(manager.broadcast(m_id, payload))
            except RuntimeError:
                # No event loop in this thread
                asyncio.run(manager.broadcast(m_id, payload))
                
        except ValueError:
            logger.error(f"LiveEventBus: Invalid meeting_id format: {event.meeting_id}")
        except Exception as e:
            logger.error(f"LiveEventBus: Failed to broadcast to UI: {e}")

# Global instance
live_event_bus = LiveEventBus()
