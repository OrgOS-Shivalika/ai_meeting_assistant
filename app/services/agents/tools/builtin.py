"""Built-in tools — wired against the DB the codebase already has.

Four real tools (lookup_meeting, search_knowledge_base, create_task,
update_task) + six stubs for integrations not yet wired.

The four real ones touch ONLY the local DB. No external HTTP calls.
That keeps this layer safe to ship before the agent harness is in
place — even if a future LLM gets confused and calls every tool, the
worst case is a few extra DB writes scoped to this org.

Integration tools (slack_post, jira_create_issue, etc.) are
registered as stubs so:
  1. Agent Control's allowed_tools suggestions don't lie about what's
     available — the names match the registry.
  2. Calling them fails LOUDLY (NotImplementedError) instead of
     silently no-op'ing, which is the right failure mode for "this
     integration isn't wired yet".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_

from app.db.models import KanbanColumn, Meeting, Task
from app.services.kanban.defaults import resolve_landing_for_meeting
from app.services.kanban.positions import position_for_end
from app.services.agents.tools.registry import Tool, ToolContext, register


# ---------------------------------------------------------------------------
# Real implementations — local DB only.
# ---------------------------------------------------------------------------


def _lookup_meeting(args: dict, ctx: ToolContext) -> dict:
    """Return summary + task counts + participant names for a meeting
    in the caller's org. Used by the LLM to ground its reasoning in
    real context before deciding what to do."""
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


def _search_knowledge_base(args: dict, ctx: ToolContext) -> dict:
    """Org-scoped meeting search. Text-matches title + summary +
    transcript via ILIKE. Cheap and predictable.

    ponytail: ILIKE not pgvector — for v1 the LLM mostly wants
    "find recent meetings about X" and substring match handles 90%
    of that. Swap to vector search via the existing RAG retriever
    when the harness lands and we know query patterns."""
    query = (args.get("query") or "").strip()
    limit = int(args.get("limit", 5))
    limit = max(1, min(20, limit))
    if not query:
        return {"results": [], "count": 0, "query": ""}

    like = f"%{query}%"
    rows = (
        ctx.db.query(Meeting)
        .filter(Meeting.organization_id == ctx.organization_id)
        .filter(
            or_(
                Meeting.title.ilike(like),
                Meeting.summary.ilike(like),
                Meeting.transcript_text.ilike(like),
            )
        )
        .order_by(Meeting.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "query": query,
        "count": len(rows),
        "results": [
            {
                "meeting_id": m.id,
                "title": m.title,
                "summary": (m.summary or "")[:280],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ],
    }


def _create_task(args: dict, ctx: ToolContext) -> dict:
    """Insert a Task row. Required: meeting_id + task. Optional:
    owner_name, due_date, priority. Lands on the org default board
    via the same routing helper meeting extractors use, so cards
    appear on the Kanban automatically."""
    mid = int(args["meeting_id"])
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
    if isinstance(due, str):
        try:
            due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
        except Exception:
            due_dt = None
    else:
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


def _update_task(args: dict, ctx: ToolContext) -> dict:
    """Patch a task's owner / status / due / priority. The LLM uses
    this when it discovers (via lookup_meeting + search) that an
    existing task needs an update — preferred over creating a
    duplicate."""
    tid = int(args["task_id"])
    # Org check via the parent meeting OR parent board — same logic
    # as `_require_task` in kanban_router.
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


# ---------------------------------------------------------------------------
# Stub handler — every not-yet-wired integration uses this so the
# error is uniform.
# ---------------------------------------------------------------------------


def _stub(name: str):
    def handler(args: dict, ctx: ToolContext) -> dict:
        raise NotImplementedError(f"tool {name!r} is registered but not wired")
    return handler


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------


def _register_all() -> None:
    # --- Real tools ---
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
        handler=_lookup_meeting,
        tags=["read", "meetings"],
    ))

    register(Tool(
        name="search_knowledge_base",
        description=(
            "Search this org's meetings by free-text query. Matches against "
            "title, summary, and transcript. Returns up to `limit` recent "
            "meetings. Use when looking for prior context on a topic."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search query."},
                "limit": {"type": "integer", "description": "Max meetings to return (1-20).", "default": 5},
            },
            "required": ["query"],
        },
        handler=_search_knowledge_base,
        tags=["read", "search"],
    ))

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
                "meeting_id": {"type": "integer", "description": "Meeting the task belongs to."},
                "task": {"type": "string", "description": "Task description (what needs to be done)."},
                "owner_name": {"type": "string", "description": "Optional owner name."},
                "due_date": {"type": "string", "description": "Optional ISO 8601 date (YYYY-MM-DD)."},
                "priority": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
            },
            "required": ["meeting_id", "task"],
        },
        handler=_create_task,
        tags=["write", "tasks"],
    ))

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
                "owner_name": {"type": "string", "description": "New owner (or null/empty to unassign)."},
                "status": {
                    "type": "string",
                    "enum": ["todo", "in_progress", "in_review", "done", "archived"],
                    "description": "New status. 'done' also marks the task complete.",
                },
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                "due_date": {"type": "string", "description": "ISO 8601 date or null to clear."},
            },
            "required": ["task_id"],
        },
        handler=_update_task,
        tags=["write", "tasks"],
    ))

    # --- Stubs — match the Agent Control suggestions list so names align ---
    for stub_name, stub_desc in [
        ("slack_post", "Post a message to Slack (NOT WIRED — placeholder)."),
        ("jira_create_issue", "Create a Jira issue (NOT WIRED — placeholder)."),
        ("github_create_pr", "Open a GitHub PR (NOT WIRED — placeholder)."),
        ("notion_create_page", "Create a Notion page (NOT WIRED — placeholder)."),
        ("crm_update_record", "Update a CRM record (NOT WIRED — placeholder)."),
        ("send_email", "Send an email (NOT WIRED — placeholder)."),
        ("create_calendar_event", "Create a calendar event (NOT WIRED — placeholder)."),
    ]:
        register(Tool(
            name=stub_name,
            description=stub_desc,
            parameters={"type": "object", "properties": {}},
            handler=_stub(stub_name),
            implemented=False,
            tags=["stub"],
        ))


_register_all()
