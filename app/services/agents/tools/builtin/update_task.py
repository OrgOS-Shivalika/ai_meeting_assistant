"""update_task — patch an existing task's owner / status / priority /
due date. Org-scoped via the parent meeting.

The LLM uses this when it discovers (via lookup_meeting + search)
that an existing task needs an update — preferred over creating a
duplicate.
"""
from __future__ import annotations

from datetime import datetime

from app.db.models import Meeting, Task
from app.services.agents.tools.registry import Tool, ToolContext, register


def handler(args: dict, ctx: ToolContext) -> dict:
    tid = int(args["task_id"])
    # Org check via the parent meeting — same logic as kanban_router's
    # `_require_task`.
    task = (
        ctx.db.query(Task)
        .join(Meeting, Task.meeting_id == Meeting.id, isouter=True)
        .filter(Task.id == tid, Meeting.organization_id == ctx.organization_id)
        .first()
    )
    if task is None:
        raise ValueError(f"task {tid} not found in this org")

    if "owner_name" in args:
        task.owner_name = (args["owner_name"] or "").strip() or None
    if "priority" in args and args["priority"]:
        pr = args["priority"].lower()
        if pr in {"low", "medium", "high"}:
            task.priority = pr
    if "due_date" in args:
        d = args["due_date"]
        if isinstance(d, str) and d:
            try:
                task.due_date = datetime.fromisoformat(d.replace("Z", "+00:00"))
            except Exception:
                pass
        elif d is None:
            task.due_date = None
    if "status" in args and args["status"]:
        st = args["status"]
        if st in {"todo", "in_progress", "in_review", "done", "archived"}:
            task.status = st
            task.is_completed = 1 if st == "done" else 0

    ctx.db.commit()
    ctx.db.refresh(task)
    return {
        "task_id": task.id,
        "task": task.task,
        "owner": task.owner_name,
        "status": task.status,
        "priority": task.priority,
        "is_completed": bool(task.is_completed),
        "due_date": task.due_date.isoformat() if task.due_date else None,
    }


register(Tool(
    name="update_task",
    description=(
        "Patch an existing task's owner / status / priority / due date. "
        "Prefer this over creating duplicates when an action item is "
        "already tracked."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer", "description": "ID of the task to update."},
            # owner_name + due_date allow null so the model can unassign
            # or clear without tripping schema validation. The handler
            # already does the right thing with None (lines above).
            "owner_name": {"type": ["string", "null"], "description": "New owner. Pass null to unassign."},
            "status": {
                "type": "string",
                "enum": ["todo", "in_progress", "in_review", "done", "archived"],
                "description": "New status. 'done' also marks the task complete.",
            },
            "priority": {"type": "string", "enum": ["low", "medium", "high"]},
            "due_date": {"type": ["string", "null"], "description": "ISO 8601 date. Pass null to clear."},
        },
        "required": ["task_id"],
    },
    handler=handler,
    tags=["write", "tasks"],
))
