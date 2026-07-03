"""Long-term memory access layer — Phase 3 of the memory implementation.

User's mental model:
  - SHORT-TERM = distilled facts (org_memory_facts, small + fast) → MemoryAccess
  - LONG-TERM  = "everything" — full record of past meetings, kept forever

Long-term isn't a new table. It's a clean read-only wrapper over the
existing tables that ALREADY hold the org's full history:
  meetings, meeting_chunks, tasks, meeting_participants.

The wrapper exists so /ask-live and future consumers don't have to
hand-write "give me the last N meetings' summaries + their tasks"
queries — that gets its own named surface.

Everything here is:
  - Org-scoped (never cross-tenant)
  - Scope-narrowable to category_id + team_id when the caller has them
  - Read-only (no bump_access, no side-effects — long-term is durable)
  - Windowed by days so a query on a 1000-meeting org doesn't blow up
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import Meeting, Task

logger = logging.getLogger(__name__)

# Optional convenience for callers that DO want a recent-only window
# (e.g. a "last 30 days" digest). Left as a constant, not a default:
# the methods now accept days=None so long-term truly means "everything"
# unless the caller opts into a window.
DEFAULT_RECENT_DAYS = 60


@dataclass
class LongTermMeeting:
    """Slim projection over Meeting for prompt-context use."""
    id: int
    title: str
    summary: str
    scheduled_at: Optional[datetime]
    created_at: datetime
    category_id: Optional[int]
    team_id: Optional[int]

    @property
    def when(self) -> str:
        """Human-friendly date for the prompt block."""
        d = self.scheduled_at or self.created_at
        return d.date().isoformat() if d else "?"


@dataclass
class LongTermTask:
    """Slim projection over Task."""
    id: int
    task: str
    owner_name: Optional[str]
    status: Optional[str]
    priority: Optional[str]
    due_date: Optional[datetime]
    is_completed: bool
    meeting_id: Optional[int]
    meeting_title: Optional[str]

    @property
    def one_liner(self) -> str:
        who = self.owner_name or "unassigned"
        due = self.due_date.date().isoformat() if self.due_date else "no date"
        return f"{self.task} — owner {who}, due {due}, status {self.status or '?'}"


class LongTermMemory:
    """Static read-only surface over the full meeting record. Mirrors
    MemoryAccess's namespace-only class pattern.

    The caller passes their existing Session; this class never opens
    its own transaction and never writes."""

    @staticmethod
    def recent_summaries(
        db: Session,
        organization_id: UUID,
        *,
        category_id: Optional[int] = None,
        team_id: Optional[int] = None,
        days: Optional[int] = None,
        limit: Optional[int] = 5,
    ) -> list[LongTermMeeting]:
        """Completed meetings' full summaries + titles for the given
        (org, category, team) scope. Ordered newest first.

        Passing `category_id` narrows to that category, `team_id`
        narrows further, both None = org-wide (all meetings the user's
        org has ever had).

        `days=None` (default) means NO time filter — every meeting in
        scope is eligible. Pass `days=30` if you want a rolling window.
        `limit=None` disables the count cap entirely."""
        stmt = (
            select(Meeting)
            .where(
                Meeting.organization_id == organization_id,
                Meeting.status == "completed",
                Meeting.summary.isnot(None),
            )
            .order_by(desc(Meeting.created_at))
        )
        if days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
            stmt = stmt.where(Meeting.created_at >= cutoff)
        if limit is not None:
            stmt = stmt.limit(max(1, limit))
        if category_id is not None:
            stmt = stmt.where(Meeting.category_id == category_id)
        if team_id is not None:
            stmt = stmt.where(Meeting.team_id == team_id)

        rows = db.execute(stmt).scalars().all()
        return [
            LongTermMeeting(
                id=r.id,
                title=r.title or f"Meeting {r.id}",
                summary=r.summary or "",
                scheduled_at=r.scheduled_at,
                created_at=r.created_at,
                category_id=r.category_id,
                team_id=r.team_id,
            )
            for r in rows
        ]

    @staticmethod
    def tasks_in_scope(
        db: Session,
        organization_id: UUID,
        *,
        category_id: Optional[int] = None,
        team_id: Optional[int] = None,
        days: Optional[int] = None,
        limit: Optional[int] = 20,
        only_open: bool = False,
    ) -> list[LongTermTask]:
        """Tasks from meetings in scope. Ordered by created_at desc so
        the freshest bubbles up first.

        `days=None` (default) means NO time filter — every task from
        every meeting in scope is eligible. `limit=None` disables the
        count cap. `only_open=True` filters to open (`is_completed=0`)
        tasks for questions like "what's still open?".
        """
        stmt = (
            select(Task, Meeting.title.label("meeting_title"))
            .join(Meeting, Task.meeting_id == Meeting.id)
            .where(Meeting.organization_id == organization_id)
            .order_by(desc(Task.created_at))
        )
        if days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
            stmt = stmt.where(Task.created_at >= cutoff)
        if limit is not None:
            stmt = stmt.limit(max(1, limit))
        if category_id is not None:
            stmt = stmt.where(Meeting.category_id == category_id)
        if team_id is not None:
            stmt = stmt.where(Meeting.team_id == team_id)
        if only_open:
            stmt = stmt.where(Task.is_completed == 0)

        out: list[LongTermTask] = []
        for row in db.execute(stmt).all():
            t = row.Task
            out.append(LongTermTask(
                id=t.id,
                task=t.task,
                owner_name=t.owner_name,
                status=t.status,
                priority=t.priority,
                due_date=t.due_date,
                is_completed=bool(t.is_completed),
                meeting_id=t.meeting_id,
                meeting_title=row.meeting_title,
            ))
        return out

    # ------------------------------------------------------------------
    # "Every meeting" convenience methods.
    #
    # These are the API surface the user asked for: long-term memory
    # must be able to reach ANY meeting in a team/category/org, not just
    # the recent ones. They're thin wrappers over the base methods with
    # days=None and no count cap — expressive at call sites and clear
    # in code review that the intent is "the full history."
    # ------------------------------------------------------------------

    @staticmethod
    def all_meetings_in_scope(
        db: Session,
        organization_id: UUID,
        *,
        category_id: Optional[int] = None,
        team_id: Optional[int] = None,
    ) -> list[LongTermMeeting]:
        """Every completed meeting in scope, no time or count limit.

        Scope precedence: team_id > category_id > org-wide. Ordered
        newest first. Consumers with a prompt budget should slice the
        return value — this method itself won't truncate."""
        return LongTermMemory.recent_summaries(
            db,
            organization_id,
            category_id=category_id,
            team_id=team_id,
            days=None,
            limit=None,
        )

    @staticmethod
    def all_tasks_in_scope(
        db: Session,
        organization_id: UUID,
        *,
        category_id: Optional[int] = None,
        team_id: Optional[int] = None,
        only_open: bool = False,
    ) -> list[LongTermTask]:
        """Every task in scope, no time or count limit."""
        return LongTermMemory.tasks_in_scope(
            db,
            organization_id,
            category_id=category_id,
            team_id=team_id,
            days=None,
            limit=None,
            only_open=only_open,
        )
