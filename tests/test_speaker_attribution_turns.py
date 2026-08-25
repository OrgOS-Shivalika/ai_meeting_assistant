"""In-room speaker attribution — turn derivation + roll-call resolution.

Guards `app/processors/speaker_attribution.py`. Companion to
`test_speaker_attribution.py`, which is left untouched so it stays an
INDEPENDENT regression guard on the online path.

What this is defending against, in priority order:

  1. Regressing online meetings. Case 1 (one human per account) works today
     and must keep producing byte-identical output. Tests marked ONLINE.
  2. Inventing a wrong name. A confident "Karthik" that is actually
     Divyansh is invisible and worse than the collapsed-speaker bug it
     replaces. Every ambiguity must resolve to "Speaker N". Tests marked
     SAFETY.
  3. Failing to separate at all. Tests marked ROOM.

The one thing NOT verified here: where the diarization index actually sits
in a compiled Recall transcript. These fixtures inject it at block level,
which is where the realtime payload carries it. Confirming the compiled
shape needs one real diarized meeting; `_dia_index` is the single place
that changes if it differs.

Run: python tests/test_speaker_attribution_turns.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.processors.speaker_attribution import (  # noqa: E402
    CAPTURE_MODE_IN_ROOM,
    CAPTURE_MODE_ONLINE,
    METHOD_ROLLCALL,
    METHOD_ROSTER,
    METHOD_UNRESOLVED,
    build_attendee_index,
    derive_turns,
    render,
    resolve_labels,
)
from app.processors.transcript_processor import TranscriptProcessor as TP  # noqa: E402


def _block(text, *, pid=100, name=None, dia=None, t0=0.0, t1=None, timed=True):
    """One block in Recall's compiled-transcript shape.

    Mirrors the real payload verified against the live DB: per-word
    `start_timestamp`/`end_timestamp` objects carrying a `relative` float,
    plus a `participant` object. `dia` injects the diarization index at
    block level.
    """
    words = text.split()
    if t1 is None:
        t1 = t0 + max(len(words) * 0.3, 0.3)
    step = (t1 - t0) / max(len(words), 1)
    out = {
        "participant": {"id": pid, "name": name},
        "words": [
            ({"text": w,
              "start_timestamp": {"relative": t0 + i * step},
              "end_timestamp": {"relative": t0 + (i + 1) * step}}
             if timed else {"text": w})
            for i, w in enumerate(words)
        ],
    }
    if dia is not None:
        out["speaker"] = dia
    return out


def _resolve(blocks, *, capture_mode=CAPTURE_MODE_IN_ROOM, attendees=None):
    turns = derive_turns(blocks, capture_mode=capture_mode)
    resolutions, diagnostics = resolve_labels(
        turns, calendar_attendees=attendees, capture_mode=capture_mode,
    )
    return turns, resolutions, diagnostics


# A second speaker, so the account is genuinely SHARED and `derive_turns`
# splits it into ("d", ...) clusters. A room fixture with only one
# diarization index is not a shared account — it is either one person or a
# total merge, both of which are covered by their own tests below.
def _second_voice(t0=300.0):
    return _block("anyway moving on", pid=100, name="Host", dia=9, t0=t0)


def _speakers(rendered):
    out = []
    for line in rendered.split("\n"):
        s = line.split(":", 1)[0]
        if s and s not in out:
            out.append(s)
    return out


def _pairs(rendered):
    """Ordered (speaker, word) pairs.

    THE online invariant. Byte-identity to `TranscriptProcessor.format` is
    NOT the guarantee — turn merging deliberately joins consecutive
    same-speaker lines, and 26 of the 164 stored transcripts legitimately
    differ that way. What must never change is who said which words, in
    order.
    """
    pairs = []
    for line in rendered.split("\n"):
        if not line:
            continue
        speaker, _, body = line.partition(": ")
        pairs.extend((speaker, w) for w in body.split())
    return pairs


# --------------------------------------------------------------- ONLINE
# Nothing here may change. These are the same guarantees
# test_speaker_attribution.py makes, re-asserted through the new path.


def test_online_output_matches_format_when_nothing_merges():
    """With no two consecutive turns from one speaker, the new path
    reproduces `TranscriptProcessor.format` byte for byte."""
    blocks = [
        _block("hello everyone", pid=100, name="Divyansh Bhardwaj", t0=0),
        _block("hi there", pid=200, name="Asha", t0=10),
        _block("morning", pid=101, name=None, t0=20),
    ]
    turns, resolutions, _ = _resolve(blocks, capture_mode=CAPTURE_MODE_ONLINE)
    assert render(turns, resolutions) == TP.format(blocks), (
        render(turns, resolutions), TP.format(blocks),
    )


def test_online_merging_changes_lines_but_never_attribution():
    """Turn merging joins consecutive same-speaker lines, so output is NOT
    byte-identical to `format()` in general — 26 of the 164 stored
    transcripts differ exactly this way, verified by corpus replay.

    The real invariant is narrower: every word keeps the same speaker.
    """
    blocks = [
        _block("first part", pid=100, name="Asha", t0=0.0, t1=1.0),
        _block("second part", pid=100, name="Asha", t0=1.2, t1=2.0),
        _block("my turn now", pid=200, name="Ravi", t0=2.5, t1=3.0),
    ]
    turns, resolutions, _ = _resolve(blocks, capture_mode=CAPTURE_MODE_ONLINE)
    new, old = render(turns, resolutions), TP.format(blocks)
    assert new != old, "fixture is meant to exercise merging"
    assert _pairs(new) == _pairs(old), (_pairs(new), _pairs(old))
    assert _speakers(new) == ["Asha", "Ravi"], _speakers(new)


def test_online_never_splits_on_diarization_index():
    """ONLINE + diarize on (misconfiguration) must NOT fragment one person.

    This is the regression the two-condition rule in `derive_turns` exists
    to prevent: index-count alone would render Asha as two speakers.
    """
    blocks = [
        _block("first part", pid=100, name="Asha", dia=0, t0=0),
        _block("second part", pid=100, name="Asha", dia=1, t0=30),
    ]
    turns, resolutions, _ = _resolve(blocks, capture_mode=CAPTURE_MODE_ONLINE)
    assert {t.speaker_key for t in turns} == {("p", 100)}, turns
    assert _speakers(render(turns, resolutions)) == ["Asha"]


def test_online_nameless_never_renders_as_None():
    blocks = [_block("hello", pid=101, name=None)]
    turns, resolutions, _ = _resolve(blocks, capture_mode=CAPTURE_MODE_ONLINE)
    out = render(turns, resolutions)
    assert "None:" not in out, out
    assert _speakers(out) == ["Participant 101"], _speakers(out)


def test_online_same_name_two_people_stay_separate():
    blocks = [
        _block("one", pid=100, name="Divyansh Bhardwaj", t0=0),
        _block("two", pid=200, name="Divyansh Bhardwaj", t0=10),
    ]
    turns, resolutions, _ = _resolve(blocks, capture_mode=CAPTURE_MODE_ONLINE)
    assert _speakers(render(turns, resolutions)) == [
        "Divyansh Bhardwaj (1)", "Divyansh Bhardwaj (2)",
    ], _speakers(render(turns, resolutions))


def test_online_participant_id_zero_survives():
    blocks = [_block("zero", pid=0, name="Zero Indexed")]
    turns, resolutions, _ = _resolve(blocks, capture_mode=CAPTURE_MODE_ONLINE)
    assert _speakers(render(turns, resolutions)) == ["Zero Indexed"]


# ----------------------------------------------------------------- ROOM


def test_room_one_account_three_voices_separate():
    """The manager's scenario: one Google account, three people in a room."""
    blocks = [
        _block("hello", pid=100, name="Divyansh Bhardwaj", dia=0, t0=0),
        _block("hi", pid=100, name="Divyansh Bhardwaj", dia=1, t0=10),
        _block("hey", pid=100, name="Divyansh Bhardwaj", dia=2, t0=20),
    ]
    turns, _, _ = _resolve(blocks)
    assert {t.speaker_key for t in turns} == {
        ("d", 100, 0), ("d", 100, 1), ("d", 100, 2),
    }, turns


def test_room_rollcall_resolves_all_three_names():
    blocks = [
        _block("this is Karthik", pid=100, name="Divyansh Bhardwaj", dia=0, t0=0),
        _block("myself Priya", pid=100, name="Divyansh Bhardwaj", dia=1, t0=5),
        _block("my name is Ravi", pid=100, name="Divyansh Bhardwaj", dia=2, t0=10),
        _block("so lets begin the review", pid=100, name="Divyansh Bhardwaj",
               dia=0, t0=40),
    ]
    turns, resolutions, diagnostics = _resolve(blocks)
    names = {r.display_name for r in resolutions.values()}
    assert names == {"Karthik", "Priya", "Ravi"}, names
    assert diagnostics.resolved_rollcall == 3, diagnostics
    assert not diagnostics.under_clustering_suspected, diagnostics


def test_room_diarization_index_zero_is_not_dropped():
    """Truthiness on an int has bitten this codebase before."""
    blocks = [
        _block("this is Karthik", pid=100, name="Host", dia=0, t0=0),
        _block("this is Priya", pid=100, name="Host", dia=1, t0=5),
    ]
    _, resolutions, _ = _resolve(blocks)
    assert resolutions[("d", 100, 0)].display_name == "Karthik", resolutions


def test_room_unresolved_cluster_becomes_speaker_n():
    blocks = [
        _block("this is Karthik", pid=100, name="Host", dia=0, t0=0),
        _block("we should ship on friday", pid=100, name="Host", dia=1, t0=5),
    ]
    _, resolutions, diagnostics = _resolve(blocks)
    assert resolutions[("d", 100, 1)].display_name == "Speaker 1", resolutions
    assert resolutions[("d", 100, 1)].method == METHOD_UNRESOLVED
    assert diagnostics.unresolved == 1, diagnostics


def test_room_hinglish_rollcall_variants():
    """Indian business meetings code-switch; the stored blobs say language_code=hi."""
    cases = {
        0: ("mera naam Karthik hai", "Karthik"),
        1: ("myself Priya", "Priya"),
        2: ("main Ravi hoon", "Ravi"),
        3: ("Anjali bol rahi hoon", "Anjali"),
        4: ("Vikram here", "Vikram"),
    }
    attendees = [
        {"email": "ravi@x.com", "displayName": "Ravi"},
        {"email": "anjali@x.com", "displayName": "Anjali"},
        {"email": "vikram@x.com", "displayName": "Vikram"},
    ]
    blocks = [
        _block(text, pid=100, name="Host", dia=dia, t0=dia * 5)
        for dia, (text, _) in cases.items()
    ]
    _, resolutions, _ = _resolve(blocks, attendees=attendees)
    for dia, (_, expected) in cases.items():
        got = resolutions[("d", 100, dia)].display_name
        assert got == expected, f"dia {dia}: expected {expected!r}, got {got!r}"


def test_room_late_joiner_gets_its_own_window():
    """A cluster first appearing at minute 20 must still be nameable.

    A single global 120s window — as the original spec specified — would
    leave this person permanently "Speaker 1".
    """
    blocks = [
        _block("this is Karthik", pid=100, name="Host", dia=0, t0=0),
        _block("okay lets continue", pid=100, name="Host", dia=0, t0=600),
        _block("sorry I am late this is Priya", pid=100, name="Host",
               dia=1, t0=1200),
    ]
    _, resolutions, _ = _resolve(blocks)
    assert resolutions[("d", 100, 1)].display_name == "Priya", resolutions


def test_room_speech_after_window_is_not_scanned():
    """Someone NAMED later in conversation is not a self-introduction."""
    blocks = [
        _block("lets start", pid=100, name="Host", dia=0, t0=0),
        _block("I think this is Karthik's call to make", pid=100, name="Host",
               dia=0, t0=900),
        _second_voice(),
    ]
    _, resolutions, _ = _resolve(blocks)
    got = resolutions[("d", 100, 0)]
    assert got.display_name != "Karthik", got
    assert got.method == METHOD_UNRESOLVED, got


# --------------------------------------------------------------- MIXED


def test_mixed_roster_and_rollcall_resolve_in_one_pass():
    """Three in a room plus one dialling in — the case a forked pipeline
    could never handle, and the reason step 5.1 must not be mode-gated."""
    blocks = [
        _block("this is Karthik", pid=100, name="Room Laptop", dia=0, t0=0),
        _block("myself Priya", pid=100, name="Room Laptop", dia=1, t0=5),
        _block("hello from home", pid=200, name="Asha Remote", dia=7, t0=10),
    ]
    turns, resolutions, _ = _resolve(blocks)

    # The remote participant produced ONE index, so she keeps roster identity.
    assert ("p", 200) in resolutions, resolutions
    assert resolutions[("p", 200)].display_name == "Asha Remote"
    assert resolutions[("p", 200)].method == METHOD_ROSTER
    # The room account produced several, so it split.
    assert resolutions[("d", 100, 0)].display_name == "Karthik"
    assert resolutions[("d", 100, 1)].display_name == "Priya"


# ---------------------------------------------------------------- SAFETY
# Every test below asserts we REFUSE to name something. A wrong name is
# the failure mode this whole design is biased against.


def test_two_names_in_one_cluster_flags_under_clustering():
    """Two CALENDAR-CONFIRMED people introducing themselves into ONE cluster
    is direct evidence the diarizer merged them. Must not pick one."""
    blocks = [
        _block("this is Karthik", pid=100, name="Host", dia=0, t0=0),
        _block("and myself Priya", pid=100, name="Host", dia=0, t0=3),
        _second_voice(),
    ]
    _, resolutions, diagnostics = _resolve(blocks, attendees=_ROOM_ATTENDEES)
    assert resolutions[("d", 100, 0)].method == METHOD_UNRESOLVED, resolutions
    assert diagnostics.under_clustering_suspected, diagnostics
    assert diagnostics.multi_name_clusters[0]["names"] == ["Karthik", "Priya"], (
        diagnostics.multi_name_clusters
    )


def test_two_uncorroborated_names_in_one_cluster_are_flagged():
    """Same shape, no calendar: still flag, still refuse to pick one."""
    blocks = [
        _block("this is Karthik", pid=100, name="Host", dia=0, t0=0),
        _block("and myself Priya", pid=100, name="Host", dia=0, t0=3),
        _second_voice(),
    ]
    _, resolutions, diagnostics = _resolve(blocks)
    got = resolutions[("d", 100, 0)]
    assert got.method == METHOD_UNRESOLVED, got
    assert got.display_name == "Speaker 0", got
    assert diagnostics.under_clustering_suspected, diagnostics


# ------------------------------------------------- short-turn filter
#
# The constant doing most of the work now that calendar corroboration is
# unavailable (instant meetings have no calendar event).


def test_long_turn_is_not_scanned_for_introductions():
    """"...and this is Karthik's call to make" inside a long sentence is not a
    self-introduction, however well it matches the pattern."""
    long_turn = (
        "okay so before we get going I just want to say this is Karthik "
        "and he will be handling the deployment work from next week onwards"
    )
    assert len(long_turn.split()) > 12
    blocks = [
        _block(long_turn, pid=100, name="Host", dia=0, t0=0),
        _second_voice(),
    ]
    _, resolutions, _ = _resolve(blocks)
    assert resolutions[("d", 100, 0)].method == METHOD_UNRESOLVED, resolutions


def test_short_turn_is_scanned():
    blocks = [
        _block("hi everyone this is Karthik from finance",
               pid=100, name="Host", dia=0, t0=0),
        _second_voice(),
    ]
    _, resolutions, _ = _resolve(blocks)
    assert resolutions[("d", 100, 0)].display_name == "Karthik", resolutions


def test_no_rollcall_no_calendar_still_separates_voices():
    """The reported expectation: even with nobody saying their name and no
    calendar event, distinct voices must render as distinct speakers."""
    blocks = [
        _block("so what do we do about the pipeline", pid=100,
               name="Divyansh Bhardwaj", dia=0, t0=0),
        _block("I think we should ship it friday", pid=100,
               name="Divyansh Bhardwaj", dia=1, t0=10),
        _block("that seems too aggressive to me", pid=100,
               name="Divyansh Bhardwaj", dia=2, t0=20),
    ]
    turns, resolutions, _ = _resolve(blocks)
    assert len({t.speaker_key for t in turns}) == 3, turns
    rendered = render(turns, resolutions)
    assert _speakers(rendered) == ["Speaker 0", "Speaker 1", "Speaker 2"], (
        _speakers(rendered)
    )
    assert "Divyansh Bhardwaj" not in rendered, rendered


_ROOM_ATTENDEES = [
    {"email": "karthik@x.com", "displayName": "Karthik"},
    {"email": "priya@x.com", "displayName": "Priya"},
]


def test_total_merge_is_flagged_when_names_are_corroborated():
    """The WORST case: the diarizer put everybody in one cluster, so
    `derive_turns` sees a single index and correctly declines to split —
    the key stays ("p", 100) with a real roster name attached.

    If the roster simply won here, a total merge would render as the account
    owner and nobody would know. Two CALENDAR-CONFIRMED people introducing
    themselves into one voice is evidence the diarizer merged them.
    """
    blocks = [
        _block("this is Karthik", pid=100, name="Conference Room 2", dia=0, t0=0),
        _block("and myself Priya", pid=100, name="Conference Room 2", dia=0, t0=3),
    ]
    turns, resolutions, diagnostics = _resolve(blocks, attendees=_ROOM_ATTENDEES)
    assert {t.speaker_key for t in turns} == {("p", 100)}, turns
    got = resolutions[("p", 100)]
    assert got.method == METHOD_UNRESOLVED, got
    assert got.display_name not in ("Karthik", "Priya"), got
    assert diagnostics.under_clustering_suspected, diagnostics


def test_total_merge_is_flagged_without_corroboration_too():
    """Instant meetings have NO calendar event, so a corroboration-only rule
    would leave this check permanently inert — the most useful signal in the
    feature, never firing.

    The short-turn filter is what makes uncorroborated detection safe: it
    scores zero false positives across all 165 stored transcripts, where the
    unfiltered scan produced 86.
    """
    blocks = [
        _block("this is Karthik", pid=100, name="Conference Room 2", dia=0, t0=0),
        _block("and myself Priya", pid=100, name="Conference Room 2", dia=0, t0=3),
    ]
    _, resolutions, diagnostics = _resolve(blocks)
    assert diagnostics.under_clustering_suspected, diagnostics
    got = resolutions[("p", 100)]
    assert got.method == METHOD_UNRESOLVED, got
    # Still never invents: neither name is adopted.
    assert got.display_name not in ("Karthik", "Priya"), got


def test_single_speaker_room_prefers_corroborated_rollcall_over_account_name():
    """One person in the room, and the account is named after the ROOM.

    "Conference Room 2" is not a human, so a calendar-confirmed
    self-introduction outranks it — the precedence inversion this feature
    needs.
    """
    blocks = [
        _block("this is Karthik", pid=100, name="Conference Room 2", dia=0, t0=0),
    ]
    _, resolutions, _ = _resolve(blocks, attendees=_ROOM_ATTENDEES)
    assert resolutions[("p", 100)].display_name == "Karthik", resolutions
    assert resolutions[("p", 100)].method == METHOD_ROLLCALL


def test_uncorroborated_rollcall_never_overrides_a_roster_name():
    """Regression from the corpus. "I'm basically proposing..." renamed
    "Divyansh Bhardwaj" to "Basically" on 36 real meetings — inventing a
    confident wrong name, which is worse than the bug being fixed."""
    blocks = [
        _block("so I'm basically proposing we ship on friday",
               pid=100, name="Divyansh Bhardwaj", dia=0, t0=0),
    ]
    _, resolutions, diagnostics = _resolve(blocks)
    got = resolutions[("p", 100)]
    assert got.display_name == "Divyansh Bhardwaj", got
    assert got.method == METHOD_ROSTER, got
    assert not diagnostics.under_clustering_suspected, diagnostics


def test_present_participles_are_never_names():
    """"I'm proposing" / "I'm working" match a strong intro pattern, and no
    stopword list enumerates every verb."""
    for phrase in ("this is proposing", "I'm working", "myself looking"):
        blocks = [
            _block(phrase, pid=100, name="Host", dia=0, t0=0),
            _second_voice(),
        ]
        _, resolutions, _ = _resolve(blocks)
        assert resolutions[("d", 100, 0)].method == METHOD_UNRESOLVED, phrase


def test_several_junk_candidates_do_not_flag_under_clustering():
    """Measured: 24 of 164 stored meetings yield 2+ distinct junk candidates
    from ordinary speech. Flagging on those would fire constantly and make
    the feature read as broken."""
    blocks = [
        _block("I'm more concerned but I'm excited and I'm curious",
               pid=100, name="Asha", dia=0, t0=0),
    ]
    _, resolutions, diagnostics = _resolve(blocks)
    assert resolutions[("p", 100)].display_name == "Asha", resolutions
    assert diagnostics.multi_name_clusters == [], diagnostics


def test_two_clusters_one_name_demotes_both():
    """If two clusters both claim "Karthik" we cannot say which is which."""
    blocks = [
        _block("this is Karthik", pid=100, name="Host", dia=0, t0=0),
        _block("this is Karthik", pid=100, name="Host", dia=1, t0=5),
    ]
    _, resolutions, diagnostics = _resolve(blocks)
    assert resolutions[("d", 100, 0)].method == METHOD_UNRESOLVED, resolutions
    assert resolutions[("d", 100, 1)].method == METHOD_UNRESOLVED, resolutions
    assert diagnostics.collided_names, diagnostics
    assert diagnostics.resolved_rollcall == 0, diagnostics


def test_stopword_is_not_accepted_as_a_name():
    """'this is important' must not produce a person called Important."""
    blocks = [
        _block("okay so this is important everyone", pid=100, name="Host",
               dia=0, t0=0),
        _second_voice(),
    ]
    _, resolutions, _ = _resolve(blocks)
    got = resolutions[("d", 100, 0)]
    assert got.display_name != "Important", got
    assert got.method == METHOD_UNRESOLVED, got


def test_junk_token_loses_to_calendar_corroborated_name():
    """"sorry I am late, this is Priya" yields both "Late" and "Priya".

    A corroborated candidate is evidence; an uncorroborated one is a guess.
    They must not cancel out as an ambiguity.
    """
    blocks = [
        _block("sorry I am late this is Priya", pid=100, name="Host", dia=0, t0=0),
        _second_voice(),
    ]
    _, resolutions, diagnostics = _resolve(
        blocks, attendees=[{"email": "priya@x.com", "displayName": "Priya"}],
    )
    assert resolutions[("d", 100, 0)].display_name == "Priya", resolutions
    assert not diagnostics.under_clustering_suspected, diagnostics


def test_weak_pattern_without_calendar_is_rejected():
    """'the main thing is' matches the Hinglish `main X` form. Weak patterns
    need calendar corroboration before they may name anybody."""
    blocks = [
        _block("the main blocker is deployment", pid=100, name="Host",
               dia=0, t0=0),
        _block("this is Karthik", pid=100, name="Host", dia=1, t0=5),
    ]
    _, resolutions, _ = _resolve(blocks)
    assert resolutions[("d", 100, 0)].method == METHOD_UNRESOLVED, resolutions


def test_weak_pattern_with_calendar_is_accepted():
    blocks = [
        _block("Vikram here", pid=100, name="Host", dia=0, t0=0),
        _second_voice(),
    ]
    _, resolutions, _ = _resolve(
        blocks, attendees=[{"email": "vikram@x.com", "displayName": "Vikram"}],
    )
    assert resolutions[("d", 100, 0)].display_name == "Vikram", resolutions
    assert resolutions[("d", 100, 0)].confidence == 0.95


def test_calendar_hit_uses_calendar_spelling_and_flags_nothing():
    """smart_format's casing is not authoritative; the invite is."""
    blocks = [
        _block("this is karthik", pid=100, name="Host", dia=0, t0=0),
        _second_voice(),
    ]
    _, resolutions, _ = _resolve(
        blocks,
        attendees=[{"email": "karthik.r@x.com", "displayName": "Karthik Raman"}],
    )
    got = resolutions[("d", 100, 0)]
    assert got.display_name == "Karthik Raman", got
    assert got.matched_email == "karthik.r@x.com", got
    assert got.needs_review is False, got


def test_uncorroborated_name_is_flagged_for_review():
    """In-room attendees are often not on the invite, so we accept — but
    never silently."""
    blocks = [
        _block("this is Karthik", pid=100, name="Host", dia=0, t0=0),
        _second_voice(),
    ]
    _, resolutions, _ = _resolve(blocks)
    got = resolutions[("d", 100, 0)]
    assert got.display_name == "Karthik", got
    assert got.needs_review is True, got
    assert got.confidence == 0.8, got


def test_ambiguous_calendar_token_is_poisoned():
    """Two attendees sharing a token must resolve to NEITHER."""
    index = build_attendee_index([
        {"email": "chris.a@x.com", "displayName": "Chris Alvarez"},
        {"email": "chris.b@x.com", "displayName": "Chris Bell"},
    ])
    assert "chris" not in index, index


def test_boolean_speaker_field_is_not_an_index():
    """`isinstance(True, int)` is True in Python, and `diarize: True` lives
    one field away in the provider config."""
    blocks = [
        {"participant": {"id": 100, "name": "Host"},
         "speaker": True,
         "words": [{"text": "hello", "start_timestamp": {"relative": 0.0},
                    "end_timestamp": {"relative": 0.5}}]},
    ]
    turns, _, _ = _resolve(blocks)
    assert turns[0].speaker_key == ("p", 100), turns
    assert turns[0].dia_index is None, turns


# ------------------------------------------------------------------ TURNS


def test_turns_merge_within_gap_and_split_beyond_it():
    blocks = [
        _block("first", pid=100, name="Asha", t0=0.0, t1=1.0),
        _block("second", pid=100, name="Asha", t0=1.5, t1=2.0),   # gap 0.5 -> merge
        _block("third", pid=100, name="Asha", t0=10.0, t1=11.0),  # gap 8.0 -> split
    ]
    turns = derive_turns(blocks, capture_mode=CAPTURE_MODE_ONLINE)
    assert len(turns) == 2, [t.text for t in turns]
    assert turns[0].text == "first second", turns[0].text
    assert turns[0].end == 2.0, turns[0].end


def test_turns_never_merge_across_speakers():
    blocks = [
        _block("mine", pid=100, name="Asha", dia=0, t0=0.0, t1=1.0),
        _block("yours", pid=100, name="Asha", dia=1, t0=1.1, t1=2.0),
    ]
    turns = derive_turns(blocks, capture_mode=CAPTURE_MODE_IN_ROOM)
    assert len(turns) == 2, [t.text for t in turns]


def test_untimed_blocks_do_not_merge():
    """A wrong merge silently joins two people's speech. Untimed pairs stay
    split on purpose — extra boundaries are harmless."""
    blocks = [
        _block("first", pid=100, name="Asha", timed=False),
        _block("second", pid=100, name="Asha", timed=False),
    ]
    turns = derive_turns(blocks, capture_mode=CAPTURE_MODE_ONLINE)
    assert len(turns) == 2, [t.text for t in turns]
    assert all(t.start is None for t in turns), turns


def test_empty_and_malformed_blocks_are_skipped():
    blocks = [
        {"participant": {"id": 100, "name": "Asha"}, "words": []},
        "not a dict",
        {"words": [{"text": "orphan"}]},
        _block("real content", pid=100, name="Asha"),
    ]
    turns = derive_turns(blocks, capture_mode=CAPTURE_MODE_ONLINE)
    texts = [t.text for t in turns]
    assert "real content" in texts, texts
    assert "" not in texts, texts


def test_untagged_block_inside_shared_account_falls_back():
    """Silence/music can leave a block with no index. It must not be
    dropped, and must not crash."""
    blocks = [
        _block("this is Karthik", pid=100, name="Host", dia=0, t0=0),
        _block("myself Priya", pid=100, name="Host", dia=1, t0=5),
        _block("untagged noise", pid=100, name="Host", dia=None, t0=10),
    ]
    turns, resolutions, _ = _resolve(blocks)
    assert ("p", 100) in {t.speaker_key for t in turns}, turns
    assert render(turns, resolutions).count("\n") == 2


def test_empty_transcript_is_not_an_error():
    for empty in (None, []):
        turns = derive_turns(empty, capture_mode=CAPTURE_MODE_IN_ROOM)
        resolutions, diagnostics = resolve_labels(turns)
        assert turns == [] and resolutions == {}
        assert diagnostics.cluster_count == 0


def test_render_output_shape_is_unchanged():
    """Downstream reads this string. Its shape is the contract."""
    blocks = [_block("hello there", pid=100, name="Asha", t0=0)]
    turns, resolutions, _ = _resolve(blocks, capture_mode=CAPTURE_MODE_ONLINE)
    assert render(turns, resolutions) == "Asha: hello there"


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
