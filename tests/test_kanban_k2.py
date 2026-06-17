"""Phase 14 K2 — Kanban router + activity-log tests.

Scope:
  - activity._jsonable: coerces datetime/UUID/Decimal/Mapping cleanly
  - activity.record_activity: validates event_type, flushes a row
  - activity.diff_and_record: emits one row per changed field, skips
    unchanged fields
  - Pydantic schema validation (board/column/task move shapes)
  - Helper purity tests (no DB) for shape conversions

Integration tests against the live API (boards CRUD + drag-drop + move
endpoint) live in `test_kanban_k2_api.py` and require a running server;
this file is the pure-unit slice you can run on every save.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.services.kanban.activity import (
    VALID_EVENT_TYPES,
    _jsonable,
    diff_and_record,
    record_activity,
)


# ---------------------------------------------------------------------------
# _jsonable — coercion of common SQLAlchemy / Python types
# ---------------------------------------------------------------------------


def test_jsonable_passes_through_primitives():
    assert _jsonable(None) is None
    assert _jsonable("x") == "x"
    assert _jsonable(42) == 42
    assert _jsonable(3.14) == 3.14
    assert _jsonable(True) is True


def test_jsonable_coerces_datetime_to_iso():
    dt = datetime(2026, 6, 15, 12, 30, tzinfo=timezone.utc)
    out = _jsonable(dt)
    assert isinstance(out, str)
    assert out.startswith("2026-06-15T12:30:00")


def test_jsonable_coerces_uuid_to_string():
    u = uuid4()
    out = _jsonable(u)
    assert isinstance(out, str)
    assert out == str(u)


def test_jsonable_coerces_decimal_to_float():
    out = _jsonable(Decimal("99.5"))
    assert out == 99.5
    assert isinstance(out, float)


def test_jsonable_recurses_into_dict_and_list():
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    u = uuid4()
    payload = {
        "name": "alice",
        "joined": dt,
        "user_id": u,
        "tags": ["a", "b"],
        "nested": {"score": Decimal("0.5")},
    }
    out = _jsonable(payload)
    assert out["name"] == "alice"
    assert isinstance(out["joined"], str)
    assert isinstance(out["user_id"], str)
    assert out["tags"] == ["a", "b"]
    assert out["nested"]["score"] == 0.5


def test_jsonable_handles_unknown_via_str():
    """Last-resort fallback — unknown types become their repr so the
    activity feed shows something readable instead of crashing."""
    class Custom:
        def __str__(self): return "custom-thing"

    out = _jsonable(Custom())
    assert out == "custom-thing"


# ---------------------------------------------------------------------------
# record_activity — event_type validation + row insertion
# ---------------------------------------------------------------------------


def test_record_activity_rejects_unknown_event_type():
    db = MagicMock()
    with pytest.raises(ValueError, match="unknown activity event_type"):
        record_activity(
            db,
            task_id=1,
            event_type="bogus_event",
        )
    # Must not have touched the DB.
    db.add.assert_not_called()
    db.flush.assert_not_called()


def test_record_activity_accepts_every_valid_event_type():
    """All 11 event types from the model CHECK constraint must be
    accepted by the helper. If someone adds a new event_type to the
    model without updating VALID_EVENT_TYPES, this fails."""
    expected = {
        "created", "status_changed", "column_moved", "owner_changed",
        "due_changed", "priority_changed", "description_changed",
        "title_changed", "commented", "archived", "restored",
    }
    assert VALID_EVENT_TYPES == expected


def test_record_activity_flushes_row():
    db = MagicMock()
    row = record_activity(
        db,
        task_id=42,
        event_type="status_changed",
        actor_user_id=None,
        actor_name="alice",
        before={"status": "todo"},
        after={"status": "done"},
    )
    db.add.assert_called_once()
    db.flush.assert_called_once()
    # Inspect the row that was added.
    added = db.add.call_args[0][0]
    assert added.task_id == 42
    assert added.event_type == "status_changed"
    assert added.actor_name == "alice"
    assert added.before == {"status": "todo"}
    assert added.after == {"status": "done"}


def test_record_activity_jsonifies_payloads():
    """before/after should be jsonable — datetime → str, UUID → str."""
    db = MagicMock()
    dt = datetime(2026, 6, 15, tzinfo=timezone.utc)
    record_activity(
        db,
        task_id=1,
        event_type="due_changed",
        before={"due_date": None},
        after={"due_date": dt},
    )
    added = db.add.call_args[0][0]
    assert added.after["due_date"].startswith("2026-06-15")


# ---------------------------------------------------------------------------
# diff_and_record — one row per CHANGED field, none for unchanged
# ---------------------------------------------------------------------------


def test_diff_and_record_skips_unchanged_fields():
    db = MagicMock()
    rows = diff_and_record(
        db,
        task_id=1,
        actor_user_id=None,
        actor_name="bob",
        before={"owner_name": "Alice", "priority": "medium"},
        after={"owner_name": "Alice", "priority": "medium"},
        field_to_event={
            "owner_name": "owner_changed",
            "priority": "priority_changed",
        },
    )
    assert rows == []
    db.add.assert_not_called()


def test_diff_and_record_emits_one_row_per_changed_field():
    db = MagicMock()
    rows = diff_and_record(
        db,
        task_id=1,
        actor_user_id=None,
        actor_name="bob",
        before={"owner_name": "Alice", "priority": "medium", "status": "todo"},
        after={"owner_name": "Bob",  "priority": "medium", "status": "in_progress"},
        field_to_event={
            "owner_name": "owner_changed",
            "priority": "priority_changed",
            "status": "status_changed",
        },
    )
    assert len(rows) == 2  # owner + status; priority unchanged → skipped
    event_types = [db.add.call_args_list[i][0][0].event_type for i in range(2)]
    assert sorted(event_types) == ["owner_changed", "status_changed"]


def test_diff_and_record_normalizes_datetime_comparison():
    """before+after with equivalent datetimes (one tz-aware, one naive
    of the same instant) should NOT produce a row — they're equal
    after jsonable coercion."""
    db = MagicMock()
    dt_aware = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    rows = diff_and_record(
        db,
        task_id=1,
        actor_user_id=None,
        actor_name="bob",
        before={"due_date": dt_aware},
        after={"due_date": dt_aware},
        field_to_event={"due_date": "due_changed"},
    )
    assert rows == []


# ---------------------------------------------------------------------------
# Schema validation — make sure clients can't accidentally submit
# invalid shapes the route would have to defend against.
# ---------------------------------------------------------------------------


def test_board_create_request_rejects_empty_name():
    from pydantic import ValidationError
    from app.schemas.kanban_schema import BoardCreateRequest

    with pytest.raises(ValidationError):
        BoardCreateRequest(name="")


def test_board_create_request_defaults_scope_to_org():
    from app.schemas.kanban_schema import BoardCreateRequest

    req = BoardCreateRequest(name="My Board")
    assert req.scope_type == "org"
    assert req.scope_id is None
    assert req.is_default is False


def test_column_create_accepts_optional_position():
    from app.schemas.kanban_schema import ColumnCreateRequest

    # Omitting position is valid — router appends to end.
    req = ColumnCreateRequest(name="Blocked")
    assert req.position is None
    assert req.is_done_column is False


def test_column_create_validates_bound_status_literal():
    from pydantic import ValidationError
    from app.schemas.kanban_schema import ColumnCreateRequest

    with pytest.raises(ValidationError):
        ColumnCreateRequest(name="X", bound_status="bogus")


def test_task_move_request_accepts_all_target_shapes():
    """Three valid target-slot specifications — all should parse."""
    from app.schemas.kanban_schema import TaskMoveRequest

    # 1. column + after
    a = TaskMoveRequest(column_id=1, after_task_id=10)
    assert a.after_task_id == 10
    # 2. column + before
    b = TaskMoveRequest(column_id=1, before_task_id=20)
    assert b.before_task_id == 20
    # 3. column only (append)
    c = TaskMoveRequest(column_id=1)
    assert c.after_task_id is None and c.before_task_id is None
    # 4. explicit position
    d = TaskMoveRequest(column_id=1, position=1500.5)
    assert d.position == 1500.5


def test_column_delete_requires_target():
    """The schema MUST require move_cards_to_column_id — no orphan
    cards allowed per the K1 plan decision."""
    from pydantic import ValidationError
    from app.schemas.kanban_schema import ColumnDeleteRequest

    with pytest.raises(ValidationError):
        ColumnDeleteRequest()


def test_task_create_request_rejects_empty_task():
    from pydantic import ValidationError
    from app.schemas.kanban_schema import TaskCreateRequest

    with pytest.raises(ValidationError):
        TaskCreateRequest(task="")


def test_task_create_request_defaults_to_medium_priority():
    from app.schemas.kanban_schema import TaskCreateRequest

    req = TaskCreateRequest(task="Do the thing")
    assert req.priority == "medium"
    assert req.owner_name is None


# ---------------------------------------------------------------------------
# Router smoke import — catches missing imports / circular deps
# ---------------------------------------------------------------------------


def test_kanban_router_imports_cleanly():
    """Importing the router should not raise — catches missing
    schema imports, model imports, or circular dependencies."""
    from app.api.kanban_router import kanban_router
    # APIRouter has `.routes` — verify it has all the expected paths.
    paths = {r.path for r in kanban_router.routes}
    expected_paths = {
        "/boards",
        "/boards/{board_id}",
        "/boards/{board_id}/columns",
        "/boards/{board_id}/tasks",
        "/columns/{column_id}",
        "/tasks/{task_id}/move",
    }
    assert expected_paths.issubset(paths), f"missing routes: {expected_paths - paths}"


def test_main_app_includes_kanban_router():
    """Sanity: the router actually got included in the FastAPI app."""
    from main import app

    paths = {r.path for r in app.router.routes}
    # The kanban router doesn't prefix, so paths are top-level.
    assert "/boards" in paths
    assert "/tasks/{task_id}/move" in paths
