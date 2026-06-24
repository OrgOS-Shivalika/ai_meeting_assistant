"""lookup_meeting — fetch a meeting's summary, status, participants,
and open task count by ID.

Read-only. Used by the LLM to ground reasoning before deciding what
to do about a meeting.
"""
from __future__ import annotations

from app.db.models import Meeting, Task
from app.services.agents.tools.registry import Tool, ToolContext, register


def handler(args: dict, ctx: ToolContext) -> dict:
    mid = int(args["meeting_id"])
    m = (
        ctx.db.query(Meeting)
        .filter(Meeting.id == mid, Meeting.organization_id == ctx.organization_id)
        .first()
    )
    if m is None:
        return {"found": False, "meeting_id": mid}
    open_tasks = (
        ctx.db.query(Task)
        .filter(Task.meeting_id == mid, Task.is_completed == 0)
        .count()
    )
    return {
        "found": True,
        "meeting_id": m.id,
        "title": m.title,
        "summary": m.summary,
        "status": m.status,
        "started_at": m.started_at.isoformat() if m.started_at else None,
        "ended_at": m.ended_at.isoformat() if m.ended_at else None,
        "duration_minutes": m.duration_minutes,
        "participants": [
            {"name": p.name, "email": p.email} for p in (m.participants or [])
        ],
        "open_task_count": open_tasks,
    }


register(Tool(
    name="lookup_meeting",
    description=(
        "Fetch a meeting's summary, status, participants, and open task "
        "count. Use this to ground reasoning before creating tasks or "
        "deciding what to do about a meeting."
    ),
    parameters={
        "type": "object",
        "properties": {
            "meeting_id": {"type": "integer", "description": "ID of the meeting to look up."},
        },
        "required": ["meeting_id"],
    },
    handler=handler,
    tags=["read", "meetings"],
))
