"""Phase 12B ship test - live decisions + rolling summary.

Validates the data-capture layer that Phase 12C (briefing composer)
will read from. Three subsystems:

  12B.1 - DecisionExtractor (LLM client mocked)
     - Returns empty list when LLM yields no decisions
     - Filters out detections below 0.5 confidence
     - Passes through speaker + timestamp metadata
     - Exception in LLM call -> returns [] (no crash)

  12B.2 - DecisionStabilizer
     - First detection creates an entry in active_decisions
     - Re-detection of the same decision (same fingerprint) updates
     - State transitions: proposed -> discussed -> confirmed
     - Confirmed decisions are immune to decay

  12B.3 - LiveSummaryTracker (LLM client mocked)
     - Cadence: <N batches -> no LLM call
     - Cadence: =N batches -> LLM call fires, state.summary updated
     - force=True bypasses cadence
     - Empty batch text -> no LLM call
     - Subsequent update receives previous summary as context
     - LLM exception -> previous summary preserved
     - LLM empty response -> previous summary preserved

  12B.4 - MeetingState shape
     - New fields exist and default empty
     - active_decisions starts empty
     - summary starts empty string

Run with:

    venv\\Scripts\\python.exe tests\\test_phase12b.py
"""
from __future__ import annotations

import os
import sys
import traceback
import types
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


results: List[Tuple[str, str, str, str]] = []


@contextmanager
def section(label: str):
    print(f"\n=== {label} ===")
    yield


def check(slice_id: str, name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except AssertionError as e:
        msg = str(e) or "assertion failed"
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [FAIL] {name} :: {msg}")
        return
    except Exception:
        msg = traceback.format_exc(limit=4).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Fake OpenAI client. The extractor + tracker both call
# `_client_factory()` which we swap to return one of these.
# ---------------------------------------------------------------------------

class _FakeChatCompletion:
    def __init__(self, content: str):
        # Mimic the OpenAI SDK response shape: response.choices[0].message.content
        self.choices = [
            types.SimpleNamespace(message=types.SimpleNamespace(content=content)),
        ]


class _FakeOpenAIClient:
    def __init__(self, content: str, raise_exc: Exception | None = None):
        self._content = content
        self._raise = raise_exc
        self.calls: List[dict] = []

        client_self = self

        class _Chat:
            class _Completions:
                @staticmethod
                def create(**kwargs):
                    client_self.calls.append(kwargs)
                    if client_self._raise:
                        raise client_self._raise
                    return _FakeChatCompletion(client_self._content)

            completions = _Completions()

        self.chat = _Chat()


def _swap_extractor_client(content_or_exc):
    """Helper to patch DecisionExtractor._client_factory; returns
    (client, restore)."""
    from app.services.live_decisions import decision_extractor as mod

    original = mod.DecisionExtractor._client_factory

    if isinstance(content_or_exc, Exception):
        client = _FakeOpenAIClient(content="", raise_exc=content_or_exc)
    else:
        client = _FakeOpenAIClient(content=content_or_exc)

    mod.DecisionExtractor._client_factory = staticmethod(lambda: client)
    return client, lambda: setattr(
        mod.DecisionExtractor, "_client_factory", staticmethod(original)
    )


def _swap_tracker_client(content_or_exc):
    from app.services.live_summary import live_summary_tracker as mod

    original = mod.LiveSummaryTracker._client_factory

    if isinstance(content_or_exc, Exception):
        client = _FakeOpenAIClient(content="", raise_exc=content_or_exc)
    else:
        client = _FakeOpenAIClient(content=content_or_exc)

    mod.LiveSummaryTracker._client_factory = staticmethod(lambda: client)
    return client, lambda: setattr(
        mod.LiveSummaryTracker, "_client_factory", staticmethod(original)
    )


def _make_chunk(text: str, speaker: str = "Alice", seq: int = 1):
    from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
    return LiveTranscriptChunk(
        speaker_id=speaker.lower(),
        speaker_name=speaker,
        text=text,
        is_final=True,
        sequence_number=seq,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# 12B.1 - DecisionExtractor
# ---------------------------------------------------------------------------

def test_extractor_returns_empty_when_llm_says_no_decisions():
    from app.services.live_decisions.decision_extractor import DecisionExtractor
    client, restore = _swap_extractor_client('{"decisions": []}')
    try:
        chunk = _make_chunk("We were just talking about the weather.", seq=1)
        raw = DecisionExtractor.extract_from_chunk(chunk, rolling_context="")
        assert raw == []
        assert len(client.calls) == 1
    finally:
        restore()


def test_extractor_filters_low_confidence():
    from app.services.live_decisions.decision_extractor import DecisionExtractor
    payload = '''{"decisions": [
        {"decision": "Maybe migrate auth", "decided_by": null,
         "decision_type": "technical", "confidence": 0.3},
        {"decision": "Migrate auth service first", "decided_by": "Team",
         "decision_type": "technical", "confidence": 0.92}
    ]}'''
    client, restore = _swap_extractor_client(payload)
    try:
        chunk = _make_chunk("we'll migrate auth first")
        raw = DecisionExtractor.extract_from_chunk(chunk, rolling_context="")
        assert len(raw) == 1, f"expected 1 (low-conf filtered), got {raw}"
        assert raw[0]["decision"] == "Migrate auth service first"
        assert raw[0]["decided_by"] == "Team"
    finally:
        restore()


def test_extractor_attaches_speaker_and_chunk_id():
    from app.services.live_decisions.decision_extractor import DecisionExtractor
    payload = '''{"decisions": [
        {"decision": "Go with option A", "decided_by": "Alice",
         "decision_type": "scope", "confidence": 0.85}
    ]}'''
    client, restore = _swap_extractor_client(payload)
    try:
        chunk = _make_chunk("Let's go with option A", speaker="Alice", seq=42)
        raw = DecisionExtractor.extract_from_chunk(chunk, rolling_context="")
        assert raw[0]["source_speaker"] == "Alice"
        assert raw[0]["transcript_chunk_id"] == 42
    finally:
        restore()


def test_extractor_swallows_llm_exception():
    from app.services.live_decisions.decision_extractor import DecisionExtractor
    _, restore = _swap_extractor_client(RuntimeError("API down"))
    try:
        chunk = _make_chunk("anything")
        raw = DecisionExtractor.extract_from_chunk(chunk, rolling_context="")
        assert raw == []
    finally:
        restore()


def test_extractor_skips_decisions_with_no_text():
    from app.services.live_decisions.decision_extractor import DecisionExtractor
    payload = '''{"decisions": [
        {"decision": "", "decided_by": "Team", "decision_type": "other", "confidence": 0.9},
        {"decision": "Valid decision", "decided_by": null,
         "decision_type": "other", "confidence": 0.8}
    ]}'''
    _, restore = _swap_extractor_client(payload)
    try:
        chunk = _make_chunk("...")
        raw = DecisionExtractor.extract_from_chunk(chunk, rolling_context="")
        assert len(raw) == 1
        assert raw[0]["decision"] == "Valid decision"
    finally:
        restore()


# ---------------------------------------------------------------------------
# 12B.2 - DecisionStabilizer
# ---------------------------------------------------------------------------

def _new_state(meeting_id: str | None = None):
    from app.services.meeting_memory.meeting_state_store import MeetingState
    return MeetingState(meeting_id or f"test-{uuid.uuid4()}")


def _raw_decision(text: str, *, decided_by=None, conf=0.7, speaker="Alice"):
    return {
        "decision": text,
        "decided_by": decided_by,
        "decision_type": "other",
        "confidence": conf,
        "source_speaker": speaker,
        "source_timestamp": datetime.now(timezone.utc),
        "transcript_chunk_id": 1,
    }


def test_stabilizer_creates_new_decision():
    from app.services.live_decisions.stabilizer import DecisionStabilizer
    state = _new_state()
    out = DecisionStabilizer.stabilize(
        state, [_raw_decision("Migrate auth service first", conf=0.7)], chunk_id=1,
    )
    assert len(out) == 1
    assert len(state.active_decisions) == 1
    d = list(state.active_decisions.values())[0]
    assert d.status == "proposed"
    assert d.mention_count == 1


def test_stabilizer_creates_discussed_when_decided_by_present():
    from app.services.live_decisions.stabilizer import DecisionStabilizer
    state = _new_state()
    DecisionStabilizer.stabilize(
        state,
        [_raw_decision("Move to staging Friday", decided_by="Ravi", conf=0.7)],
        chunk_id=1,
    )
    d = list(state.active_decisions.values())[0]
    assert d.status == "discussed", f"expected 'discussed', got {d.status!r}"
    assert d.decided_by == "Ravi"


def test_stabilizer_dedups_repeat_mention():
    """Same exact text twice => one row, mention_count=2."""
    from app.services.live_decisions.stabilizer import DecisionStabilizer
    state = _new_state()
    DecisionStabilizer.stabilize(
        state, [_raw_decision("Migrate auth first", conf=0.6)], chunk_id=1,
    )
    DecisionStabilizer.stabilize(
        state, [_raw_decision("Migrate auth first", conf=0.7)], chunk_id=2,
    )
    assert len(state.active_decisions) == 1
    d = list(state.active_decisions.values())[0]
    assert d.mention_count == 2
    # Confidence aggregates upward
    assert d.confidence > 0.6


def test_stabilizer_promotes_to_confirmed_when_confidence_high():
    from app.services.live_decisions.stabilizer import DecisionStabilizer
    state = _new_state()
    # First mention: 0.7 with decided_by -> discussed
    DecisionStabilizer.stabilize(
        state,
        [_raw_decision("Approve release on Friday", decided_by="PM", conf=0.7)],
        chunk_id=1,
    )
    # Multiple subsequent mentions should push confidence > 0.85
    for i in range(2, 6):
        DecisionStabilizer.stabilize(
            state,
            [_raw_decision("Approve release on Friday", decided_by="PM", conf=0.9)],
            chunk_id=i,
        )
    d = list(state.active_decisions.values())[0]
    assert d.confidence >= 0.85, f"confidence not high enough: {d.confidence}"
    assert d.status == "confirmed", f"expected 'confirmed', got {d.status!r}"


def test_stabilizer_confirmed_immune_to_decay():
    from app.services.live_decisions import stabilizer as st_mod
    from app.services.live_decisions.stabilizer import DecisionStabilizer
    state = _new_state()
    # Build a confirmed decision.
    DecisionStabilizer.stabilize(
        state,
        [_raw_decision("Adopt monorepo", decided_by="Team", conf=0.9)],
        chunk_id=1,
    )
    for i in range(2, 6):
        DecisionStabilizer.stabilize(
            state,
            [_raw_decision("Adopt monorepo", decided_by="Team", conf=0.95)],
            chunk_id=i,
        )
    d = list(state.active_decisions.values())[0]
    assert d.status == "confirmed"
    conf_before = d.confidence

    # Now run many decay cycles with no new mentions (and use a chunk_id
    # far enough past the decay window).
    original_decay_after = st_mod._DECAY_AFTER_CHUNKS
    st_mod._DECAY_AFTER_CHUNKS = 0
    try:
        for chunk_id in range(20, 30):
            DecisionStabilizer.stabilize(state, [], chunk_id=chunk_id)
        assert d.confidence == conf_before, (
            f"confirmed decision should not decay: {conf_before} -> {d.confidence}"
        )
    finally:
        st_mod._DECAY_AFTER_CHUNKS = original_decay_after


def test_stabilizer_decay_applies_to_proposed_decisions():
    from app.services.live_decisions import stabilizer as st_mod
    from app.services.live_decisions.stabilizer import DecisionStabilizer
    state = _new_state()
    DecisionStabilizer.stabilize(
        state, [_raw_decision("Maybe try X", conf=0.5)], chunk_id=1,
    )
    d = list(state.active_decisions.values())[0]
    conf_before = d.confidence
    original_decay_after = st_mod._DECAY_AFTER_CHUNKS
    st_mod._DECAY_AFTER_CHUNKS = 0
    try:
        DecisionStabilizer.stabilize(state, [], chunk_id=99)
        assert d.confidence < conf_before, (
            f"proposed decision should decay: {conf_before} -> {d.confidence}"
        )
    finally:
        st_mod._DECAY_AFTER_CHUNKS = original_decay_after


def test_stabilizer_logs_state_evolution():
    from app.services.live_decisions.stabilizer import DecisionStabilizer
    state = _new_state()
    DecisionStabilizer.stabilize(
        state, [_raw_decision("Adopt X", conf=0.6)], chunk_id=1,
    )
    DecisionStabilizer.stabilize(
        state,
        [_raw_decision("Adopt X", decided_by="Team", conf=0.6)],
        chunk_id=2,
    )
    d = list(state.active_decisions.values())[0]
    # Should have: initial 'proposed', then transition to 'discussed'
    transitions = [(e.from_state, e.to_state) for e in d.evolution]
    assert ("none", "proposed") in transitions
    assert ("proposed", "discussed") in transitions


# ---------------------------------------------------------------------------
# 12B.3 - LiveSummaryTracker
# ---------------------------------------------------------------------------

def test_summary_cadence_skips_below_interval():
    from app.services.live_summary import live_summary_tracker as st_mod
    from app.services.live_summary.live_summary_tracker import LiveSummaryTracker
    client, restore = _swap_tracker_client("Should not be called.")
    state = _new_state()
    # Force interval to 3 so the first 2 calls skip.
    original = st_mod._SUMMARY_BATCH_INTERVAL
    st_mod._SUMMARY_BATCH_INTERVAL = 3
    try:
        out1 = LiveSummaryTracker.maybe_update(state, "first batch text")
        out2 = LiveSummaryTracker.maybe_update(state, "second batch text")
        assert out1 is None and out2 is None
        assert len(client.calls) == 0
        assert state.summary == ""
    finally:
        st_mod._SUMMARY_BATCH_INTERVAL = original
        restore()


def test_summary_fires_at_interval_and_updates_state():
    from app.services.live_summary import live_summary_tracker as st_mod
    from app.services.live_summary.live_summary_tracker import LiveSummaryTracker
    client, restore = _swap_tracker_client(
        "The team discussed sprint progress and reviewed API migration."
    )
    state = _new_state()
    original = st_mod._SUMMARY_BATCH_INTERVAL
    st_mod._SUMMARY_BATCH_INTERVAL = 2
    try:
        LiveSummaryTracker.maybe_update(state, "batch one content here")
        result = LiveSummaryTracker.maybe_update(state, "batch two content here")
        assert result is not None and "sprint" in result.lower()
        assert state.summary == result.strip()
        assert state.summary_updated_at is not None
        assert len(client.calls) == 1
        # Counter reset after fire.
        assert state.summary_batches_since_update == 0
    finally:
        st_mod._SUMMARY_BATCH_INTERVAL = original
        restore()


def test_summary_force_bypasses_cadence():
    from app.services.live_summary import live_summary_tracker as st_mod
    from app.services.live_summary.live_summary_tracker import LiveSummaryTracker
    client, restore = _swap_tracker_client(
        "Brief summary of the meeting so far."
    )
    state = _new_state()
    original = st_mod._SUMMARY_BATCH_INTERVAL
    st_mod._SUMMARY_BATCH_INTERVAL = 999  # never naturally fires
    try:
        result = LiveSummaryTracker.maybe_update(state, "early batch", force=True)
        assert result is not None
        assert state.summary == "Brief summary of the meeting so far."
        assert len(client.calls) == 1
    finally:
        st_mod._SUMMARY_BATCH_INTERVAL = original
        restore()


def test_summary_empty_batch_text_is_noop():
    from app.services.live_summary.live_summary_tracker import LiveSummaryTracker
    client, restore = _swap_tracker_client("Should not be called.")
    state = _new_state()
    try:
        LiveSummaryTracker.maybe_update(state, "")
        LiveSummaryTracker.maybe_update(state, "   ")
        assert len(client.calls) == 0
        assert state.summary == ""
        assert state.summary_batches_since_update == 0
    finally:
        restore()


def test_summary_subsequent_update_includes_previous_in_prompt():
    from app.services.live_summary import live_summary_tracker as st_mod
    from app.services.live_summary.live_summary_tracker import LiveSummaryTracker
    state = _new_state()
    original = st_mod._SUMMARY_BATCH_INTERVAL
    st_mod._SUMMARY_BATCH_INTERVAL = 1
    try:
        # First update: client returns initial summary.
        client1, restore1 = _swap_tracker_client(
            "First summary: team kicked off sprint."
        )
        try:
            LiveSummaryTracker.maybe_update(state, "kickoff discussion")
            assert state.summary == "First summary: team kicked off sprint."
        finally:
            restore1()

        # Second update: client returns updated summary; verify previous
        # was passed in the prompt.
        client2, restore2 = _swap_tracker_client(
            "Updated: team kicked off sprint and reviewed migration plan."
        )
        try:
            LiveSummaryTracker.maybe_update(state, "migration plan discussion")
            assert "migration" in state.summary.lower()
            # The second prompt must include the previous summary text.
            second_prompt = client2.calls[0]["messages"][-1]["content"]
            assert "PREVIOUS SUMMARY:" in second_prompt
            assert "First summary: team kicked off sprint." in second_prompt
        finally:
            restore2()
    finally:
        st_mod._SUMMARY_BATCH_INTERVAL = original


def test_summary_llm_exception_preserves_previous():
    from app.services.live_summary import live_summary_tracker as st_mod
    from app.services.live_summary.live_summary_tracker import LiveSummaryTracker
    state = _new_state()
    state.summary = "Pre-existing summary."
    original = st_mod._SUMMARY_BATCH_INTERVAL
    st_mod._SUMMARY_BATCH_INTERVAL = 1
    try:
        _, restore = _swap_tracker_client(RuntimeError("API down"))
        try:
            result = LiveSummaryTracker.maybe_update(state, "new content")
            assert result is None
            assert state.summary == "Pre-existing summary.", (
                "previous summary should be preserved on LLM failure"
            )
        finally:
            restore()
    finally:
        st_mod._SUMMARY_BATCH_INTERVAL = original


def test_summary_llm_empty_response_preserves_previous():
    from app.services.live_summary import live_summary_tracker as st_mod
    from app.services.live_summary.live_summary_tracker import LiveSummaryTracker
    state = _new_state()
    state.summary = "Pre-existing summary."
    original = st_mod._SUMMARY_BATCH_INTERVAL
    st_mod._SUMMARY_BATCH_INTERVAL = 1
    try:
        _, restore = _swap_tracker_client("   ")  # whitespace
        try:
            result = LiveSummaryTracker.maybe_update(state, "new content")
            assert result is None
            assert state.summary == "Pre-existing summary."
        finally:
            restore()
    finally:
        st_mod._SUMMARY_BATCH_INTERVAL = original


def test_summary_strips_label_prefixes():
    from app.services.live_summary import live_summary_tracker as st_mod
    from app.services.live_summary.live_summary_tracker import LiveSummaryTracker
    state = _new_state()
    original = st_mod._SUMMARY_BATCH_INTERVAL
    st_mod._SUMMARY_BATCH_INTERVAL = 1
    try:
        _, restore = _swap_tracker_client('Summary: The team made progress today.')
        try:
            LiveSummaryTracker.maybe_update(state, "content")
            assert not state.summary.startswith("Summary:")
            assert "team made progress" in state.summary
        finally:
            restore()
    finally:
        st_mod._SUMMARY_BATCH_INTERVAL = original


# ---------------------------------------------------------------------------
# 12B.4 - MeetingState shape
# ---------------------------------------------------------------------------

def test_meeting_state_has_new_fields_with_defaults():
    state = _new_state()
    # Phase 12B additions
    assert hasattr(state, "active_decisions")
    assert state.active_decisions == {}
    assert hasattr(state, "summary")
    assert state.summary == ""
    assert hasattr(state, "summary_updated_at")
    assert state.summary_updated_at is None
    assert hasattr(state, "summary_batches_since_update")
    assert state.summary_batches_since_update == 0
    # Phase 11 fields still intact
    assert state.active_tasks == {}
    assert state.decisions == []


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    suites = [
        ("12B.1 DecisionExtractor", [
            ("empty when LLM returns no decisions", test_extractor_returns_empty_when_llm_says_no_decisions),
            ("filters low-confidence detections", test_extractor_filters_low_confidence),
            ("attaches speaker + chunk id", test_extractor_attaches_speaker_and_chunk_id),
            ("swallows LLM exception", test_extractor_swallows_llm_exception),
            ("skips empty decision text", test_extractor_skips_decisions_with_no_text),
        ]),
        ("12B.2 DecisionStabilizer", [
            ("creates new decision", test_stabilizer_creates_new_decision),
            ("creates 'discussed' when decided_by present", test_stabilizer_creates_discussed_when_decided_by_present),
            ("dedups repeat mention", test_stabilizer_dedups_repeat_mention),
            ("promotes to confirmed at high confidence", test_stabilizer_promotes_to_confirmed_when_confidence_high),
            ("confirmed immune to decay", test_stabilizer_confirmed_immune_to_decay),
            ("decay applies to proposed", test_stabilizer_decay_applies_to_proposed_decisions),
            ("state evolution logged", test_stabilizer_logs_state_evolution),
        ]),
        ("12B.3 LiveSummaryTracker", [
            ("cadence skips below interval", test_summary_cadence_skips_below_interval),
            ("fires at interval and updates state", test_summary_fires_at_interval_and_updates_state),
            ("force bypasses cadence", test_summary_force_bypasses_cadence),
            ("empty batch text is no-op", test_summary_empty_batch_text_is_noop),
            ("second update includes previous", test_summary_subsequent_update_includes_previous_in_prompt),
            ("LLM exception preserves previous", test_summary_llm_exception_preserves_previous),
            ("LLM empty response preserves previous", test_summary_llm_empty_response_preserves_previous),
            ("strips label prefixes", test_summary_strips_label_prefixes),
        ]),
        ("12B.4 MeetingState shape", [
            ("new fields exist with defaults", test_meeting_state_has_new_fields_with_defaults),
        ]),
    ]

    for label, cases in suites:
        with section(label):
            for name, fn in cases:
                check(label.split()[0], name, fn)

    print()
    print("=== Phase 12B summary ===")
    passes = sum(1 for r in results if r[2] == "PASS")
    fails = sum(1 for r in results if r[2] == "FAIL")
    print(f"  PASS: {passes}")
    print(f"  FAIL: {fails}")
    print(f"  total: {len(results)}")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
