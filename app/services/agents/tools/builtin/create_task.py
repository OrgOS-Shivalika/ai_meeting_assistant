"""create_task — insert a Task row, landed on the org's default
Kanban board's "To Do" column.

Uses the same routing helper meeting extractors use, so manually-
created tasks appear on the Kanban automatically.
"""
from __future__ import annotations

from datetime import datetime

from app.db.models import Meeting, Task
from app.services.agents.tools.registry import Tool, ToolContext, register
from app.services.kanban.defaults import resolve_landing_for_meeting
from app.services.kanban.positions import position_for_end


def handler(args: dict, ctx: ToolContext) -> dict:
    # Resolve meeting_id from ctx by default — the harness sets it to
    # the meeting currently being analyzed. An explicit args value
    # overrides (e.g. a future skill creating cross-meeting tasks).
    raw_mid = args.get("meeting_id", ctx.meeting_id)
    if raw_mid is None:
        raise ValueError(
            "create_task requires a meeting_id — neither args nor ToolContext provided one"
        )
    mid = int(raw_mid)
    text = (args.get("task") or "").strip()
    if not text:
        raise ValueError("task text required")

    m = (
        ctx.db.query(Meeting)
        .filter(Meeting.id == mid, Meeting.organization_id == ctx.organization_id)
        .first()
    )
    if m is None:
        raise ValueError(f"meeting {mid} not found in this org")

    board_id, column_id = resolve_landing_for_meeting(
        ctx.db, m.organization_id, status="todo",
    )
    position = position_for_end(ctx.db, column_id) if column_id else None

    due = args.get("due_date")
    due_dt = None
    if isinstance(due, str):
        try:
            due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
        except Exception:
            due_dt = None

    task = Task(
        meeting_id=mid,
        task=text,
        owner_name=(args.get("owner_name") or "").strip() or None,
        priority=(args.get("priority") or "medium").lower(),
        due_date=due_dt,
        is_completed=0,
        status="todo",
        board_id=board_id,
        column_id=column_id,
        position=position,
    )
    ctx.db.add(task)
    ctx.db.commit()
    ctx.db.refresh(task)
    return {
        "task_id": task.id,
        "meeting_id": task.meeting_id,
        "task": task.task,
        "owner": task.owner_name,
        "status": task.status,
        "board_id": task.board_id,
        "column_id": task.column_id,
    }


register(Tool(
    name="create_task",
    description=(
        "Create a new task attached to a meeting. Lands on the org's "
        "default Kanban board. Use when an action item surfaces that "
        "isn't already in the task list."
    ),
    parameters={
        "type": "object",
        "properties": {
            # meeting_id intentionally omitted — the harness injects
            # it via ToolContext, so the model doesn't need to remember
            # or guess it. Pass it explicitly only when targeting a
            # different meeting than the active one (rare).
            "task": {"type": "string", "description": "Task description (what needs to be done)."},
            "owner_name": {"type": "string", "description": "Optional owner name."},
            "due_date": {"type": "string", "description": "Optional ISO 8601 date (YYYY-MM-DD)."},
            "priority": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
        },
        "required": ["task"],
    },
    handler=handler,
    tags=["write", "tasks"],
))
