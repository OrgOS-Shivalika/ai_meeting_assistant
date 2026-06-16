"""
Tests for the Phase 13D revised dateless-task pipeline.

Covers the bug where the extractor's ISO `due_date` was being stripped
in the LiveTask layer, causing every resolved relative deadline ("by
Friday") to land as NULL in `tasks.due_date`.

Scope:
  - LiveTask model carries `due_date`
  - TaskStabilizer copies `due_date` on create
  - Stabilizer is sticky: a later vague mention does NOT erase an
    earlier resolved date
  - Stabilizer overwrites when a new resolved date arrives
  - LiveTaskPersistence._parse_date only accepts ISO; rejects raw phrases
  - Tasks without a date are tracked (no row dropped)
"""
from datetime import datetime

import pytest

from app.services.live_tasks.live_task_models import LiveTask
from app.services.live_tasks.stabilizer import TaskStabilizer
from app.services.live_tasks.persistence import LiveTaskPersistence
from app.services.meeting_memory.meeting_state_store import MeetingState


def _raw(task: str, **overrides):
    """Build a raw extractor detection with reasonable defaults."""
    base = {
        "task": task,
        "owner": None,
        "type": "unassigned_task",
        "deadline": None,
        "due_date": None,
        "confidence": 0.7,
        "source_speaker": "Alice",
        "source_timestamp": 0,
        "transcript_chunk_id": 1,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# LiveTask model
# ---------------------------------------------------------------------------


def test_live_task_has_due_date_field():
    t = LiveTask(
        id="t1", task="Ship the feature", fingerprint="fp1",
        status="detected", confidence=0.7,
        source_speaker="Alice", source_transcript_chunk_id=1,
        due_date="2026-06-12",
    )
    assert t.due_date == "2026-06-12"


def test_live_task_due_date_defaults_to_none():
    t = LiveTask(
        id="t1", task="Ship the feature", fingerprint="fp1",
        status="detected", confidence=0.7,
        source_speaker="Alice", source_transcript_chunk_id=1,
    )
    assert t.due_date is None


# ---------------------------------------------------------------------------
# TaskStabilizer — create path
# ---------------------------------------------------------------------------


def test_stabilizer_copies_due_date_on_create():
    state = MeetingState(meeting_id="m1")
    raw = _raw("Ship the feature", deadline="by Friday", due_date="2026-06-12")

    [task] = TaskStabilizer.stabilize(state, [raw], chunk_id=1)

    assert task.due_date == "2026-06-12"
    assert task.deadline == "by Friday"


def test_stabilizer_create_with_no_date_is_dateless():
    state = MeetingState(meeting_id="m1")
    raw = _raw("Ship the feature")

    [task] = TaskStabilizer.stabilize(state, [raw], chunk_id=1)

    assert task.due_date is None
    assert task.deadline is None


# ---------------------------------------------------------------------------
# TaskStabilizer — update path (sticky resolution)
# ---------------------------------------------------------------------------


def test_stabilizer_sticky_date_not_erased_by_null():
    state = MeetingState(meeting_id="m1")
    first = _raw("Ship the feature", deadline="by Friday", due_date="2026-06-12")
    [task] = TaskStabilizer.stabilize(state, [first], chunk_id=1)

    # A later mention with no date should NOT wipe the resolved one.
    second = _raw("Ship the feature")
    TaskStabilizer.stabilize(state, [second], chunk_id=2)

    assert task.due_date == "2026-06-12"
    assert task.deadline == "by Friday"


def test_stabilizer_overwrites_date_when_new_one_arrives():
    state = MeetingState(meeting_id="m1")
    first = _raw("Ship the feature", deadline="by Friday", due_date="2026-06-12")
    [task] = TaskStabilizer.stabilize(state, [first], chunk_id=1)

    # Speaker refined the deadline; new resolved date wins.
    second = _raw(
        "Ship the feature", deadline="by next Monday", due_date="2026-06-15"
    )
    TaskStabilizer.stabilize(state, [second], chunk_id=2)

    assert task.due_date == "2026-06-15"
    assert task.deadline == "by next Monday"


def test_stabilizer_dateless_then_dated_resolves():
    state = MeetingState(meeting_id="m1")
    # First mention has no date.
    first = _raw("Ship the feature")
    [task] = TaskStabilizer.stabilize(state, [first], chunk_id=1)
    assert task.due_date is None

    # Speaker adds a deadline later.
    second = _raw("Ship the feature", deadline="tomorrow", due_date="2026-06-12")
    TaskStabilizer.stabilize(state, [second], chunk_id=2)

    assert task.due_date == "2026-06-12"


# ---------------------------------------------------------------------------
# LiveTaskPersistence._parse_date — ISO-only contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("iso", [
    "2026-06-12",
    "2026-06-12T15:30:00",
    "2026-06-12T15:30:00+00:00",
    "2026-06-12T15:30:00Z",
])
def test_parse_date_accepts_iso(iso):
    out = LiveTaskPersistence._parse_date(iso)
    assert isinstance(out, datetime)
    assert out.year == 2026 and out.month == 6 and out.day == 12


@pytest.mark.parametrize("phrase", [
    "by Friday",
    "tomorrow",
    "next week",
    "कल तक",
    "Friday tak",
    "soon",
    "",
])
def test_parse_date_rejects_natural_language(phrase):
    assert LiveTaskPersistence._parse_date(phrase) is None


def test_parse_date_handles_none():
    assert LiveTaskPersistence._parse_date(None) is None


def test_parse_date_handles_non_string():
    assert LiveTaskPersistence._parse_date(123) is None
    assert LiveTaskPersistence._parse_date({"foo": "bar"}) is None


# ---------------------------------------------------------------------------
# End-to-end shape: payload from a stabilized LiveTask carries due_date
# ---------------------------------------------------------------------------


def test_model_dump_carries_due_date_for_live_event_payload():
    """The live event payload is `task.model_dump()`. Persistence reads
    `payload.get("due_date")` — this guards the contract between layers."""
    state = MeetingState(meeting_id="m1")
    raw = _raw("Ship the feature", deadline="by Friday", due_date="2026-06-12")
    [task] = TaskStabilizer.stabilize(state, [raw], chunk_id=1)

    payload = task.model_dump()

    assert payload["due_date"] == "2026-06-12"
    assert payload["deadline"] == "by Friday"
    # And persistence can parse it cleanly.
    parsed = LiveTaskPersistence._parse_date(payload["due_date"])
    assert isinstance(parsed, datetime)


def test_model_dump_for_dateless_task():
    state = MeetingState(meeting_id="m1")
    [task] = TaskStabilizer.stabilize(state, [_raw("Ship the feature")], chunk_id=1)

    payload = task.model_dump()

    # Dateless is a valid, tracked state — both fields are None and the
    # downstream parser returns None without raising.
    assert payload["due_date"] is None
    assert payload["deadline"] is None
    assert LiveTaskPersistence._parse_date(payload["due_date"]) is None
