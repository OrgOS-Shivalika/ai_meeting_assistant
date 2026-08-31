"""Speaker attribution — the participant ID is the identity, the name is
only a display label.

Every bug this guards came from treating the NAME as the key. Found
2026-08-07 by replaying stored transcripts:

  - 4 meetings where one name maps to two participant ids. Recall assigns
    ids 100 and 200 to two different people both called "Divyansh
    Bhardwaj" (meeting 4421). The live path keyed on the name and merged
    them into ONE speaker for the whole transcript.
  - 71 meetings containing a speaker with name=null. The batch path used
    `participant.get("name", "Unknown")`, whose default only fires when
    the key is ABSENT — Recall sends it present-with-null, so the label
    became the literal string "None".
  - `if p_id:` dropped participant id 0 entirely (truthiness on an int).

Notes are generated from the batch output, so the "None" bug reached the
analyzer on 71 meetings.

Run: python tests/test_speaker_attribution.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.processors.transcript_processor import TranscriptProcessor as TP  # noqa: E402


def _block(pid, name, text="hello there"):
    """One block in Recall's compiled-transcript shape."""
    return {"participant": {"id": pid, "name": name},
            "words": [{"text": w} for w in text.split()]}


def _speakers(formatted):
    out = []
    for line in formatted.split("\n"):
        s = line.split(":", 1)[0]
        if s and s not in out:
            out.append(s)
    return out


# ---------------------------------------------------------------- batch


def test_batch_nameless_never_renders_as_None():
    """The exact meeting-4860 payload. `None:` must never reach the LLM."""
    out = TP.format([_block(101, None)])
    assert "None:" not in out, f"literal 'None' speaker leaked: {out!r}"
    assert _speakers(out) == ["Participant 101"], _speakers(out)


def test_batch_same_name_two_people_stay_separate():
    """Meeting 4421: ids 100 and 200 are both 'Divyansh Bhardwaj'."""
    out = TP.format([
        _block(100, "Divyansh Bhardwaj"), _block(200, "Divyansh Bhardwaj"),
        _block(300, "smart logix"),
    ])
    assert _speakers(out) == [
        "Divyansh Bhardwaj (1)", "Divyansh Bhardwaj (2)", "smart logix",
    ], _speakers(out)


def test_batch_multiple_nameless_are_not_collapsed():
    """Three unnamed people are three speakers, not one bucket."""
    out = TP.format([_block(101, None), _block(102, None), _block(103, None)])
    assert len(_speakers(out)) == 3, _speakers(out)


def test_batch_participant_id_zero_survives():
    """`if p_id:` dropped id 0 from the label map."""
    out = TP.format([_block(0, "Zero Indexed"), _block(1, "One")])
    assert _speakers(out) == ["Zero Indexed", "One"], _speakers(out)


def test_batch_empty_string_name_treated_as_nameless():
    out = TP.format([_block(7, "   ")])
    assert _speakers(out) == ["Participant 7"], _speakers(out)


def test_batch_label_count_matches_distinct_ids():
    """The core invariant: N distinct ids -> N distinct labels."""
    blocks = [_block(i, None if i % 2 else "Sam") for i in range(1, 7)]
    out = TP.format(blocks)
    assert len(_speakers(out)) == 6, _speakers(out)


def test_batch_tolerates_missing_participant_key():
    out = TP.format([{"words": [{"text": "orphan"}]}])
    assert "None:" not in out
    assert _speakers(out) == ["Unknown Speaker"], _speakers(out)


# ----------------------------------------------------------------- live


def test_live_same_name_two_people_stay_separate():
    """The reported bug: the live path merged them."""
    seen = {}
    a = TP.incremental_speaker_label(100, "Divyansh Bhardwaj", seen)
    b = TP.incremental_speaker_label(200, "Divyansh Bhardwaj", seen)
    assert a != b, f"two people merged into one live speaker: {a!r}"
    assert (a, b) == ("Divyansh Bhardwaj", "Divyansh Bhardwaj (2)"), (a, b)


def test_live_label_is_stable_across_utterances():
    """The same person must not drift labels mid-meeting."""
    seen = {}
    first = TP.incremental_speaker_label(100, "Asha", seen)
    TP.incremental_speaker_label(200, "Asha", seen)
    again = TP.incremental_speaker_label(100, "Asha", seen)
    assert first == again == "Asha", (first, again)


def test_live_nameless_uses_id():
    seen = {}
    assert TP.incremental_speaker_label(101, None, seen) == "Participant 101"


def test_live_id_zero_and_missing_id():
    seen = {}
    assert TP.incremental_speaker_label(0, None, seen) == "Participant 0"
    assert TP.incremental_speaker_label(None, None, seen) == "Unknown Speaker"
    assert TP.incremental_speaker_label(None, "Ravi", seen) == "Ravi"


# ------------------------------------------------- diarization (in-room)
#
# In-room capture: N people share ONE Google account, so Recall reports a
# single participant id for every utterance and the transcription
# provider's diarization index is the only thing separating them.
# `deepgram_provider` sets `diarize: False` today, so these paths are
# dormant — but the webhook previously fed the integer index in as a NAME,
# which crashed on index >= 1.


def test_diarization_index_is_never_treated_as_a_name():
    """`(1).strip()` raised AttributeError before the isinstance guard."""
    seen = {}
    assert TP.incremental_speaker_label(100, 1, seen) == "Participant 100"


def test_in_room_one_account_many_voices_separate():
    """The manager's scenario: one Google account, six people in a room."""
    seen = {}
    labels = [
        TP.incremental_speaker_label(100, None, seen, dia_speaker=i)
        for i in (0, 1, 2, 0, 1)
    ]
    assert labels == ["Speaker 0", "Speaker 1", "Speaker 2", "Speaker 0", "Speaker 1"], labels
    assert len(set(seen.values())) == 3, seen


def test_diarization_index_zero_is_not_dropped():
    seen = {}
    assert TP.incremental_speaker_label(100, None, seen, dia_speaker=0) == "Speaker 0"


def test_roster_name_beats_diarization_index():
    """Online meeting with diarize on: the roster is exact, diarization is
    a guess. One named participant must not fragment across indices."""
    seen = {}
    a = TP.incremental_speaker_label(100, "Asha", seen, dia_speaker=0)
    b = TP.incremental_speaker_label(100, "Asha", seen, dia_speaker=1)
    assert a == b == "Asha", (a, b)
    assert len(set(seen.values())) == 1, seen


def test_diarization_absent_keeps_existing_behaviour():
    """Online meetings (diarize off) must be byte-identical to before."""
    seen = {}
    assert TP.incremental_speaker_label(101, None, seen) == "Participant 101"
    assert TP.incremental_speaker_label(100, "Ravi", seen) == "Ravi"


# --------------------------------------- capture-mode precedence (Stage 3)
#
# THE fix. Before this, `incremental_speaker_label` discarded the diarization
# index whenever a roster name was present — and a laptop joining a Meet from
# a room ALWAYS presents a name, often not even a person's ("Conference Room
# 2"). So enabling diarization changed nothing observable, and the failure was
# indistinguishable from the diarizer not working.


def test_in_room_diarization_beats_a_named_account():
    """One named account, three voices in the room -> three speakers.

    The exact scenario the feature exists for, and the exact case the old
    `if real:` precedence silently collapsed.
    """
    seen = {}
    labels = [
        TP.incremental_speaker_label(
            100, "Conference Room 2", seen, dia_speaker=i,
            capture_mode="in_room",
        )
        for i in (0, 1, 2, 0)
    ]
    assert labels == ["Speaker 0", "Speaker 1", "Speaker 2", "Speaker 0"], labels
    assert len(set(seen.values())) == 3, seen


def test_in_room_never_uses_the_account_name_as_a_speaker():
    """The account name belongs to the laptop, not to any one person in the
    room, and we cannot know which of them owns it."""
    seen = {}
    label = TP.incremental_speaker_label(
        100, "Divyansh Bhardwaj", seen, dia_speaker=1, capture_mode="in_room",
    )
    assert label == "Speaker 1", label
    assert "Divyansh" not in str(seen.values()), seen


def test_online_is_unchanged_by_the_new_parameter():
    """Default and explicit ONLINE must both keep roster precedence."""
    for mode in (None, "online"):
        seen = {}
        kwargs = {} if mode is None else {"capture_mode": mode}
        a = TP.incremental_speaker_label(100, "Asha", seen, dia_speaker=0, **kwargs)
        b = TP.incremental_speaker_label(100, "Asha", seen, dia_speaker=1, **kwargs)
        assert a == b == "Asha", (mode, a, b)
        assert len(set(seen.values())) == 1, (mode, seen)


def test_unknown_capture_mode_degrades_to_online():
    """Safe direction: treating a room as online reproduces the old bug,
    whereas treating an online call as a room would replace exact names with
    anonymous numbers."""
    seen = {}
    label = TP.incremental_speaker_label(
        100, "Asha", seen, dia_speaker=0, capture_mode="IN ROOM",
    )
    assert label == "Asha", label


def test_in_room_without_diarization_still_uses_the_roster():
    """Diarization off, or a block the provider never tagged. Falls back
    rather than dropping the utterance."""
    seen = {}
    assert TP.incremental_speaker_label(
        100, "Asha", seen, capture_mode="in_room",
    ) == "Asha"


def test_in_room_nameless_account_unchanged():
    """The pre-existing in-room case (dial-ins, unreadable profiles) must
    behave exactly as it did before capture_mode existed."""
    seen = {}
    assert TP.incremental_speaker_label(
        101, None, seen, dia_speaker=2, capture_mode="in_room",
    ) == "Speaker 2"


# ------------------------------------------- batch routing (format, Stage 3)


def test_format_online_route_is_byte_identical():
    """The online route must not go through turn derivation at all."""
    blocks = [_block(100, "Asha", "hello"), _block(200, "Ravi", "hi")]
    assert TP.format(blocks) == TP.format(blocks, capture_mode="online")
    assert _speakers(TP.format(blocks, capture_mode="online")) == ["Asha", "Ravi"]


def test_format_in_room_separates_a_shared_account():
    def _dia_block(pid, name, dia, text):
        b = _block(pid, name, text)
        b["speaker"] = dia
        return b

    blocks = [
        _dia_block(100, "Conference Room 2", 0, "this is Karthik"),
        _dia_block(100, "Conference Room 2", 1, "myself Priya"),
    ]
    out = TP.format(blocks, capture_mode="in_room")
    assert _speakers(out) == ["Karthik", "Priya"], _speakers(out)
    assert "Conference Room 2" not in out, out


def test_format_detailed_returns_resolutions_and_diagnostics():
    """Stage 4 persists these; they must not require re-deriving turns."""
    blocks = [_block(100, "Asha", "hello")]
    text, resolutions, diagnostics = TP.format_detailed(blocks)
    assert text == TP.format(blocks)
    assert resolutions == {} and diagnostics is None, (resolutions, diagnostics)

    b = _block(100, "Host", "this is Karthik")
    b["speaker"] = 0
    b2 = _block(100, "Host", "myself Priya")
    b2["speaker"] = 1
    _, resolutions, diagnostics = TP.format_detailed(
        [b, b2], capture_mode="in_room",
    )
    assert len(resolutions) == 2, resolutions
    assert diagnostics is not None and diagnostics.cluster_count == 2, diagnostics


def test_format_in_room_flags_under_clustering():
    """Two CALENDAR-CONFIRMED introductions in one voice cluster: the
    diarizer merged people. Corroboration is required — uncorroborated pairs
    occur in ordinary speech on 24 of the 164 stored transcripts."""
    b = _block(100, "Host", "this is Karthik and myself Priya")
    b["speaker"] = 0
    b2 = _block(100, "Host", "anyway moving on")
    b2["speaker"] = 1
    _, _, diagnostics = TP.format_detailed(
        [b, b2], capture_mode="in_room",
        calendar_attendees=[
            {"email": "karthik@x.com", "displayName": "Karthik"},
            {"email": "priya@x.com", "displayName": "Priya"},
        ],
    )
    assert diagnostics.under_clustering_suspected, diagnostics


def test_format_in_room_never_renames_a_roster_speaker_from_junk():
    """Corpus regression: in_room mode replaced "Divyansh Bhardwaj" with
    "Basically" on 36 real meetings before corroboration was required."""
    b = _block(100, "Divyansh Bhardwaj", "so I'm basically proposing this")
    out = TP.format([b], capture_mode="in_room")
    assert _speakers(out) == ["Divyansh Bhardwaj"], _speakers(out)


def test_live_and_batch_agree_on_speaker_COUNT():
    """The two paths number differently by design — live cannot rewrite
    lines already sent — but they must never disagree on HOW MANY people
    spoke, which is what attribution correctness rests on."""
    pairs = [(100, "Divyansh Bhardwaj"), (200, "Divyansh Bhardwaj"),
             (300, "smart logix"), (101, None)]
    batch = set(TP.build_speaker_labels(pairs).values())
    seen = {}
    for pid, nm in pairs:
        TP.incremental_speaker_label(pid, nm, seen)
    assert len(batch) == len(set(seen.values())) == 4, (batch, seen)


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
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    sys.exit(1 if failed else 0)
