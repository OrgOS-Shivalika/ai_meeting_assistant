"""create_calendar_event — STUB. Create a calendar event.

To wire:
  1. Google Calendar is ALREADY auth'd (see app/services/google_calendar_service.py)
     — wrap that here. Outlook is a separate add.
  2. Implement handler calling `create_calendar_event()` from
     google_calendar_service with the active user's OAuth tokens
  3. Expand parameters with `title`, `start`, `end`, `attendees`,
     `description`
  4. Flip implemented=True
"""
from __future__ import annotations

from app.services.agents.tools.registry import Tool, register
from app.services.agents.tools.builtin._stub import make_handler


register(Tool(
    name="create_calendar_event",
    description="Create a calendar event (NOT WIRED — placeholder).",
    parameters={"type": "object", "properties": {}},
    handler=make_handler("create_calendar_event"),
    implemented=False,
    tags=["stub", "calendar"],
))
