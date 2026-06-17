"""Single writer for the `task_activity` audit table.

Every mutation that the Kanban surface performs against a task should
flow through `record_activity` so the per-card activity feed stays
complete. Callers pass the actor (the current user — or None for
system events like the auto-extraction backfill), the event_type, and
JSON-able `before` / `after` snapshots of the fields that changed.

Design notes:
  - `event_type` is validated client-side here (the DB also has a
    CHECK constraint, but we want a clear ValueError early not an
    IntegrityError at commit time).
  - `before` / `after` are stored as JSONB. `_jsonable` normalizes
    datetime / Decimal / UUID into JSON-safe primitives.
  - The function flushes (NOT commits) — callers control transaction
    boundaries. This lets one PATCH endpoint emit several activity
    rows in the same transaction (e.g. column-move + status-change
    on a drag-drop).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import TaskActivity
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


VALID_EVENT_TYPES = frozenset({
    "created",
    "status_changed",
    "column_moved",
    "owner_changed",
    "due_changed",
    "priority_changed",
    "description_changed",
    "title_changed",
    "commented",
    "archived",
    "restored",
})


def _jsonable(value: Any) -> Any:
    """Convert SQLAlchemy / Pydantic / Python values into JSON-safe
    primitives. JSONB handles dict/list/str/int/float/bool/null;
    everything else needs coercion."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    # Fall back to str() for unknown types — at least the activity feed
    # shows something readable rather than blowing up the request.
    return str(value)


def record_activity(
    db: Session,
    *,
    task_id: int,
    event_type: str,
    actor_user_id: Optional[UUID] = None,
    actor_name: Optional[str] = None,
    before: Optional[Mapping[str, Any]] = None,
    after: Optional[Mapping[str, Any]] = None,
) -> TaskActivity:
    """Append an audit row. Returns the inserted object (with id
    populated after flush) so callers can chain.

    Raises ValueError if `event_type` isn't in the allowlist — caught
    early to avoid an IntegrityError at commit time and to keep typos
    out of the audit log.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(
            f"unknown activity event_type {event_type!r}; "
            f"expected one of {sorted(VALID_EVENT_TYPES)}"
        )

    row = TaskActivity(
        task_id=task_id,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        event_type=event_type,
        before=_jsonable(before) if before is not None else None,
        after=_jsonable(after) if after is not None else None,
    )
    db.add(row)
    db.flush()  # populate id without committing — caller controls txn
    return row


def diff_and_record(
    db: Session,
    *,
    task_id: int,
    actor_user_id: Optional[UUID],
    actor_name: Optional[str],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    field_to_event: Mapping[str, str],
) -> list[TaskActivity]:
    """Convenience wrapper — emits one activity row per field that
    actually changed.

    `field_to_event` maps field names → event_type strings, e.g.
        {"owner_name": "owner_changed", "status": "status_changed"}

    Only fields present in BOTH `before` and `after` AND with
    different values produce a row. Fields where before == after are
    silently skipped so a PATCH that touches a field without changing
    it doesn't bloat the audit log.

    Returns the list of inserted rows (empty if nothing changed).
    """
    rows: list[TaskActivity] = []
    for field, event_type in field_to_event.items():
        b = before.get(field)
        a = after.get(field)
        # Normalize for comparison — JSON-coerce both sides so
        # datetime/UUID compare correctly.
        if _jsonable(b) == _jsonable(a):
            continue
        rows.append(record_activity(
            db,
            task_id=task_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            before={field: b},
            after={field: a},
        ))
    return rows
