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
