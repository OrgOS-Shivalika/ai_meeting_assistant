"""Single source of truth for the string-enumerated columns in the schema.

The DB keeps these as plain ``String`` columns policed by CHECK constraints
(see models.py). These ``str``-based enums centralise the allowed values so
Python code stops passing bare string literals around, while remaining 100%
compatible with the existing columns:

* Each enum subclasses ``str``, so ``MeetingStatus.PENDING == "pending"`` and
  it serialises to the plain string in JSON / SQLAlchemy binds — no column
  type change, no migration.
* ``values()`` yields the raw strings, and ``check_in()`` builds the exact
  ``col IN ('a', 'b', ...)`` SQL used by the CHECK constraints, so the
  constraint and the enum can never drift apart.

Usage
-----
    from app.utils.enums import MeetingStatus, check_in

    meeting.status = MeetingStatus.PROCESSING          # instead of "processing"

    __table_args__ = (
        CheckConstraint(check_in("status", TaskStatus), name="ck_tasks_status"),
    )
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Type


class StrEnum(str, Enum):
    """Base for string enums.

    Subclassing ``str`` makes members behave as their string value in
    comparisons, f-strings, JSON, and SQLAlchemy String binds, so these are
    drop-in replacements for the current string literals.

    Members are declared with ``auto()`` and the value is the member name
    verbatim — so ``IN_PROGRESS = auto()`` yields ``"IN_PROGRESS"``. Write the
    name once, in capitals; the stored string is that exact upper-case token.
    """

    def _generate_next_value_(name, start, count, last_values):  # noqa: N805
        # Called by auto(): the DB string is the member name as-is (UPPERCASE).
        return name

    def __str__(self) -> str:  # so f"{MeetingStatus.PENDING}" -> "pending"
        return self.value

    @classmethod
    def values(cls) -> list[str]:
        """All member values, in definition order."""
        return [m.value for m in cls]


def check_in(column: str, enum_cls: Type[StrEnum]) -> str:
    """Build the ``column IN ('a', 'b', ...)`` SQL for a CHECK constraint.

    Keeps the constraint's allowed set locked to the enum so adding a member
    only requires a migration that re-runs this same expression.
    """
    rendered = ", ".join(f"'{v}'" for v in enum_cls.values())
    return f"{column} IN ({rendered})"


# ---------------------------------------------------------------------------
# Meeting lifecycle
# ---------------------------------------------------------------------------
class MeetingStatus(StrEnum):
    """meetings.status — main post-meeting pipeline lifecycle."""

    PENDING = auto()
    PROCESSING = auto()
    COMPLETED = auto()
    FAILED = auto()


class MeetingPlatform(StrEnum):
    """meetings.meeting_platform."""

    GOOGLE_MEET = auto()
    ZOOM = auto()
    TEAMS = auto()
    WEBEX = auto()


class EmbeddingStatus(StrEnum):
    """*.embedding_status — Phase 2 vector-embedding pipeline, decoupled from
    the main meeting lifecycle."""

    PENDING = auto()
    PROCESSING = auto()
    EMBEDDED = auto()
    EMPTY = auto()
    FAILED = auto()
    SKIPPED = auto()


class GraphStatus(StrEnum):
    """*.graph_status — Phase 3 graph-extraction pipeline."""

    PENDING = auto()
    PROCESSING = auto()
    EXTRACTED = auto()
    FAILED = auto()
    SKIPPED = auto()


class ClosingBriefingStatus(StrEnum):
    """meetings.closing_briefing_status — Phase 12 end-of-meeting recap state
    machine. Also the idempotency guard for MEETING_ENDED webhooks.

    NOTE: values are still lowercase (explicit, NOT auto()) and DEFERRED from
    the uppercase switch. This field is entangled with the `closing_briefings`
    audit table: `final_status` (from PlaybackResult via _terminal_status) is
    written to BOTH columns, so they share a vocabulary — including the extra
    terminal values below that only arise on the playback path. Converting to
    uppercase must be done together with the audit table + its CHECK.
    """

    PENDING = "pending"
    WINDING_DOWN = "winding_down"
    ENDED = "ended"
    SPOKEN = "spoken"
    SKIPPED = "skipped"
    FAILED = "failed"
    # Playback-path terminals shared with closing_briefings.status:
    PLAYBACK_FAILED = "playback_failed"
    UPLOAD_FAILED = "upload_failed"
    TIMEOUT = "timeout"
    STORAGE_NOT_CONFIGURED = "storage_not_configured"


# ---------------------------------------------------------------------------
# Tasks / Kanban
# ---------------------------------------------------------------------------
class TaskStatus(StrEnum):
    """tasks.status. Kept in lockstep with tasks.is_completed in the
    orchestration layer (status='done' <-> is_completed=1).

    NOTE: values are still lowercase (explicit, NOT auto()) — unlike the other
    enums, Task.status is entangled with KanbanColumn.bound_status, the
    is_completed sync, the LiveTask state machine, and an overloaded "done"
    literal (Recall webhook event code / SSE event name). It stays lowercase
    until that dependency closure is converted deliberately.
    """

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    ARCHIVED = "archived"
