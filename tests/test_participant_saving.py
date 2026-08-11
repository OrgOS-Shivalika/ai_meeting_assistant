"""Participant persistence — the rules that decide whether an attendee
gets a `participants` row at all.

Why this file exists: on 2026-08-03 the Railway DB held 62 completed
meetings with ZERO participant rows and 58 meetings with fewer rows than
their own transcript contained. Both traced to one guard in
`save_participants` — `if p_id and name` — which dropped every attendee
Recall reported as `{"id": 101, "name": null}` (dial-ins, guests, and
anyone whose platform profile Recall can't read). A third of the
mismatches went the other way: meetings carrying exactly 2x or 3x their
real attendees, because a re-run appended a second full copy.

Since `participants.user_id` is an authorization input, a dropped row is
not cosmetic — it silently denies that person access to the meeting.

Run: python tests/test_participant_saving.py
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import Participant  # noqa: E402
from app.pipelines.meeting_pipeline import MeetingPipeline  # noqa: E402


# --------------------------------------------------------------------------
# Fakes. No DB — `save_participants` only reaches the session for the
# already-saved recall_ids and (when an email resolved) a User lookup,
# and these cases never resolve an email.
# --------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, existing_recall_ids=()):
        self.added = []
        self.commits = 0
        self._existing = [(r,) for r in existing_recall_ids]

    def query(self, *entities):
        # Participant.recall_id renders as 'participants.recall_id';
        # anything else (User) has no rows to return here.
        if entities and "recall_id" in str(entities[0]):
            return _FakeQuery(self._existing)
        return _FakeQuery([])

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


class _FakeMeeting:
    def __init__(self):
        self.id = 4835
        self.meeting_url = "https://meet.google.com/abc-defg-hij"
        self.organization_id = uuid.uuid4()
        self.user = None
        self.google_event_data = None
        self.google_event_id = None


def _block(pid, name):
    """One transcript block in Recall's compiled-transcript shape."""
    return {"participant": {"id": pid, "name": name}, "words": [{"text": "hi"}]}


def _save(transcript, bot_data=None, existing=()):
    db = _FakeDB(existing)
    MeetingPipeline().save_participants(db, _FakeMeeting(), transcript, bot_data)
    return db.added


def _names(rows):
    return sorted(r.name for r in rows)


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def test_nameless_participant_is_still_saved():
    """The exact payload behind the zero-participant meetings: one
    speaker, `name: null`. It used to produce no rows at all."""
    rows = _save([_block(101, None)])
    assert len(rows) == 1, f"nameless attendee dropped: {rows}"
    assert rows[0].recall_id == "101"
    assert rows[0].name == "Participant 101"


def test_named_and_nameless_both_saved():
    """Meeting 4834 on Railway: two ids in the transcript, one saved."""
    rows = _save([_block(100, "Divyansh Bhardwaj"), _block(101, None)])
    assert len(rows) == 2, f"expected both attendees, got {_names(rows)}"
    assert _names(rows) == ["Divyansh Bhardwaj", "Participant 101"]


def test_participant_id_zero_is_not_dropped():
    """`if p_id and name` also ate id=0. Truthiness is the wrong test
    for an integer id."""
    rows = _save([_block(0, "Zero Indexed")])
    assert len(rows) == 1, "participant id 0 dropped by a truthiness check"
    assert rows[0].recall_id == "0"


def test_real_name_beats_placeholder_either_order():
    """A nameless sighting must never overwrite a name we already hold,
    and a later real name must upgrade an earlier placeholder."""
    late = _save([_block(7, None), _block(7, "Asha")])
    assert _names(late) == ["Asha"], f"real name lost when it arrived late: {_names(late)}"

    early = _save([_block(7, "Asha"), _block(7, None)])
    assert _names(early) == ["Asha"], f"placeholder clobbered a real name: {_names(early)}"


def test_bot_metadata_supplies_non_speakers():
    """Someone who joined but never spoke is only in bot_data."""
    rows = _save(
        [_block(100, "Divyansh Bhardwaj")],
        bot_data={"meeting_participants": [
            {"id": 100, "name": "Divyansh Bhardwaj"},
            {"id": 205, "name": "Silent Observer"},
            {"id": 206, "name": None},
        ]},
    )
    assert _names(rows) == ["Divyansh Bhardwaj", "Participant 206", "Silent Observer"]


def test_rerun_does_not_duplicate():
    """Re-running analysis on a meeting must not append a second copy —
    that is the 2x/3x participant count seen on 7 Railway meetings."""
    rows = _save(
        [_block(100, "Divyansh Bhardwaj"), _block(101, None)],
        existing=("100", "101"),
    )
    assert rows == [], f"re-run duplicated attendees: {_names(rows)}"


def test_rerun_still_adds_newly_seen_attendee():
    """Skipping must be per-id, not a blanket bail-out — a late joiner
    found on the second pass still needs a row."""
    rows = _save(
        [_block(100, "Divyansh Bhardwaj"), _block(101, None)],
        existing=("100",),
    )
    assert _names(rows) == ["Participant 101"], f"late joiner missed: {_names(rows)}"


def test_rows_carry_no_trusted_match_source_without_a_calendar_hit():
    """Provenance describes a link. With no calendar data there is no
    email and no user, so `match_source` must stay NULL — otherwise a
    guessed row would start granting meeting access."""
    rows = _save([_block(101, None)])
    assert rows[0].match_source is None
    assert rows[0].user_id is None
    assert rows[0].email is None


def _fake_row_matches_model():
    """Guard: the fakes above only prove anything if the real Participant
    columns are still the ones being written."""
    cols = set(Participant.__table__.columns.keys())
    for required in ("recall_id", "name", "user_id", "match_source", "is_organizer"):
        assert required in cols, f"Participant.{required} disappeared — update this test"


if __name__ == "__main__":
    _fake_row_matches_model()
    checks = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for check in checks:
        try:
            check()
            print(f"  ok  {check.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {check.__name__}: {exc}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    sys.exit(1 if failed else 0)
