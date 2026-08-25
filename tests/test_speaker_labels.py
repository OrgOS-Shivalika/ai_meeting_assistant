"""Speaker-label persistence — the one artifact that cannot be re-derived.

Stage 4 of SPEAKER_ATTRIBUTION_PLAN.md. Turns come back out of
`meetings.transcript_raw` at any time, but "voice cluster 1 is Karthik" is
either evidence captured at the time or a human correction. So the rules that
matter here are about not losing or duplicating it:

  1. Re-running the pipeline must not duplicate rows. Meetings once carried 2x
     their real participants for exactly this reason.
  2. A human correction must NEVER be overwritten by a later automatic pass.
  3. Room-speaker attendee rows must grant NO access — `user_id` and
     `match_source` stay NULL even when a calendar match was found, because
     `permissions._attended_meeting_ids` gates meeting reads on those two
     fields and a name spoken into a mic is not authentication.
  4. Online meetings must write nothing at all.

No DB: a fake session records what would have been written. Same idiom as
`tests/test_participant_saving.py`.

Run: python tests/test_speaker_labels.py
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.processors.speaker_attribution import (  # noqa: E402
    METHOD_ROLLCALL, METHOD_ROSTER, METHOD_UNRESOLVED,
    Resolution, parse_key, serialize_key,
)
from app.services import speaker_labels  # noqa: E402


# --------------------------------------------------------------------------
# Fakes
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

    def __iter__(self):
        return iter(self._rows)


class _FakeDB:
    def __init__(self, mappings=(), participant_recall_ids=()):
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self._mappings = list(mappings)
        self._participants = [(r,) for r in participant_recall_ids]

    def query(self, *entities):
        target = str(entities[0]) if entities else ""
        if "recall_id" in target:
            return _FakeQuery(self._participants)
        return _FakeQuery(self._mappings)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _FakeMeeting:
    def __init__(self, mid=4901):
        self.id = mid


def _res(name, method=METHOD_ROLLCALL, *, dia=None, email=None, review=False):
    return Resolution(
        display_name=name, method=method, confidence=0.95 if email else 0.8,
        matched_email=email, needs_review=review, diarization_label=dia,
    )


class _StoredRow:
    """Stands in for a `label_mappings` row already in the table."""

    def __init__(self, speaker_key, display_name, corrected_by=None):
        self.speaker_key = speaker_key
        self.display_name = display_name
        self.method = METHOD_ROLLCALL
        self.confidence = 0.8
        self.matched_email = None
        self.needs_review = False
        self.diarization_label = None
        self.corrected_by = corrected_by
        self.corrected_at = None


# ------------------------------------------------------- key serialization


def test_keys_round_trip():
    for key in (("p", 100), ("p", 0), ("d", 100, 0), ("d", 100, 7)):
        assert parse_key(serialize_key(key)) == key, key


def test_serialized_keys_are_distinct_across_shapes():
    """"p:100" and "d:100:0" must never collide — they are different people."""
    assert serialize_key(("p", 100)) != serialize_key(("d", 100, 0))


def test_participant_id_zero_survives_serialization():
    """Truthiness on an int has bitten this codebase repeatedly."""
    assert parse_key(serialize_key(("d", 0, 0))) == ("d", 0, 0)


def test_bad_keys_raise():
    for junk in ("", "x:1", "p", "p:1:2:3", "d:1", None):
        try:
            parse_key(junk)
        except ValueError:
            continue
        raise AssertionError(f"accepted junk key {junk!r}")


# ----------------------------------------------------------- persistence


def test_online_meeting_writes_nothing():
    db = _FakeDB()
    assert speaker_labels.persist_resolutions(db, 1, {}) == (0, 0)
    assert db.added == [] and db.commits == 0


def test_first_run_inserts_one_row_per_speaker():
    db = _FakeDB()
    resolutions = {
        ("d", 100, 0): _res("Karthik", dia=0),
        ("d", 100, 1): _res("Priya", dia=1),
        ("p", 200): _res("Asha Remote", METHOD_ROSTER),
    }
    inserted, updated = speaker_labels.persist_resolutions(db, 4901, resolutions)
    assert (inserted, updated) == (3, 0), (inserted, updated)
    keys = sorted(r.speaker_key for r in db.added)
    assert keys == ["d:100:0", "d:100:1", "p:200"], keys


def test_rerun_updates_instead_of_duplicating():
    """A Celery redelivery or rerun_analysis.py must not append a second copy."""
    stored = [_StoredRow("d:100:0", "Speaker 0")]
    db = _FakeDB(mappings=stored)
    inserted, updated = speaker_labels.persist_resolutions(
        db, 4901, {("d", 100, 0): _res("Karthik", dia=0)},
    )
    assert (inserted, updated) == (0, 1), (inserted, updated)
    assert db.added == [], db.added
    assert stored[0].display_name == "Karthik"


def test_human_correction_is_never_overwritten():
    """THE rule. A manual fix is the only recovery from a bad automatic match;
    silently reverting it is worse than never offering the correction."""
    stored = [_StoredRow("d:100:0", "Priya", corrected_by=uuid.uuid4())]
    db = _FakeDB(mappings=stored)
    inserted, updated = speaker_labels.persist_resolutions(
        db, 4901, {("d", 100, 0): _res("Karthik", dia=0)},
    )
    assert (inserted, updated) == (0, 0), (inserted, updated)
    assert stored[0].display_name == "Priya", stored[0].display_name


def test_participant_id_stored_as_string():
    """Must match `participants.recall_id`, which is String while Recall
    sends an int — otherwise the join is awkward."""
    db = _FakeDB()
    speaker_labels.persist_resolutions(db, 4901, {("d", 100, 2): _res("Ravi", dia=2)})
    assert db.added[0].participant_id == "100", db.added[0].participant_id
    assert db.added[0].diarization_label == 2


def test_review_flag_is_carried_through():
    db = _FakeDB()
    speaker_labels.persist_resolutions(
        db, 4901,
        {("d", 100, 0): _res("Karthik", dia=0, review=True),
         ("d", 100, 1): _res("Priya", dia=1, email="priya@x.com")},
    )
    by_key = {r.speaker_key: r for r in db.added}
    assert by_key["d:100:0"].needs_review is True
    assert by_key["d:100:1"].needs_review is False
    assert by_key["d:100:1"].matched_email == "priya@x.com"


# ------------------------------------------------------- room speaker rows


def test_room_speakers_get_attendee_rows():
    db = _FakeDB()
    added = speaker_labels.save_room_speakers(
        db, _FakeMeeting(),
        {("d", 100, 0): _res("Karthik", dia=0),
         ("d", 100, 1): _res("Priya", dia=1)},
    )
    assert added == 2, added
    assert sorted(p.recall_id for p in db.added) == ["dia:0", "dia:1"]
    assert sorted(p.name for p in db.added) == ["Karthik", "Priya"]


def test_room_speaker_rows_grant_no_access():
    """A spoken name is not authentication. `user_id` and `match_source` gate
    meeting READ access in `permissions._attended_meeting_ids`."""
    db = _FakeDB()
    speaker_labels.save_room_speakers(
        db, _FakeMeeting(),
        {("d", 100, 0): _res("Karthik", dia=0, email="karthik@x.com")},
    )
    row = db.added[0]
    assert row.user_id is None, row.user_id
    assert row.match_source is None, row.match_source
    # Email is still carried, for display and assignee suggestions only.
    assert row.email == "karthik@x.com"


def test_room_speakers_are_idempotent():
    """Re-run must not append a second copy — the `dia:` prefix means the
    existing skip-not-replace logic recognizes them."""
    db = _FakeDB(participant_recall_ids=["dia:0", "100"])
    added = speaker_labels.save_room_speakers(
        db, _FakeMeeting(),
        {("d", 100, 0): _res("Karthik", dia=0),
         ("d", 100, 1): _res("Priya", dia=1)},
    )
    assert added == 1, added
    assert db.added[0].recall_id == "dia:1"


def test_roster_keys_never_become_room_speakers():
    """A remote participant already has a real Recall row."""
    db = _FakeDB()
    added = speaker_labels.save_room_speakers(
        db, _FakeMeeting(), {("p", 200): _res("Asha", METHOD_ROSTER)},
    )
    assert added == 0 and db.added == []


def test_synthetic_recall_id_cannot_collide_with_a_real_one():
    """Recall ids are integers, so a prefixed string is always distinct."""
    rid = speaker_labels.room_speaker_recall_id(0)
    assert rid == "dia:0"
    assert not rid.isdigit()


# ------------------------------------------------------------ corrections


def test_correction_marks_the_row_and_locks_it():
    stored = [_StoredRow("d:100:0", "Speaker 0")]
    db = _FakeDB(mappings=stored)
    actor = uuid.uuid4()
    row = speaker_labels.apply_correction(
        db, 4901, "d:100:0", "  Karthik  ", corrected_by=actor,
    )
    assert row.display_name == "Karthik", row.display_name
    assert row.method == "manual" and row.confidence == 1.0
    assert row.needs_review is False
    assert row.corrected_by == actor and row.corrected_at is not None


def test_correction_rejects_a_corrupt_key():
    db = _FakeDB(mappings=[_StoredRow("d:100:0", "Speaker 0")])
    try:
        speaker_labels.apply_correction(db, 4901, "nonsense", "Karthik")
    except ValueError:
        return
    raise AssertionError("accepted a corrupt speaker key")


def test_correction_rejects_an_empty_name():
    db = _FakeDB(mappings=[_StoredRow("d:100:0", "Speaker 0")])
    try:
        speaker_labels.apply_correction(db, 4901, "d:100:0", "   ")
    except ValueError:
        return
    raise AssertionError("accepted an empty display name")


def test_unresolved_rows_sort_first_for_review():
    rows = [
        _StoredRow("d:100:1", "Priya"),
        _StoredRow("d:100:0", "Speaker 0"),
    ]
    rows[1].method = METHOD_UNRESOLVED
    rows[1].needs_review = True
    db = _FakeDB(mappings=rows)
    ordered = speaker_labels.mappings_for_meeting(db, 4901)
    assert ordered[0].display_name == "Speaker 0", [r.display_name for r in ordered]


if __name__ == "__main__":
    checks = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for c in checks:
        try:
            c()
            print(f"  ok  {c.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {c.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {c.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    sys.exit(1 if failed else 0)
