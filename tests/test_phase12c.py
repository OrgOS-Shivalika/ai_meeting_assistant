"""Phase 12C ship test - briefing composer.

What this test covers:

  12C.1 - Empty / sparse state
     - state never written -> returns None
     - state with only empty summary, no decisions, no tasks -> None
     - state with only a short (< 4 words) summary -> None
     - state with one decision -> composes (minimum signal met)

  12C.2 - Section assembly
     - Opening + closing are hardcoded (LLM cannot change them)
     - Disabled section yields None for that field even if LLM
       produced text for it
     - sections_included list correctly reflects what was emitted
     - full_text concatenates in the right order

  12C.3 - Task routing
     - Task with owner -> goes to assigned bucket
     - Task with owner=None -> goes to unassigned bucket
     - Decisions sorted by confidence (highest first)

  12C.4 - Length cap
     - Composer respects max_seconds via WPM math (max_words = wpm * sec / 60)
     - Overshoot triggers retry with tighter cap
     - Final script below MIN_SECONDS returns None

  12C.5 - Failure handling
     - LLM exception -> returns None (caller decides)
     - LLM invalid JSON -> returns None
     - LLM returns all-empty sections + no opening/closing -> None

  12C.6 - Audit / metadata
     - script.model_used reflects settings
     - script.prompt_version reflects settings
     - script.source_state_summary counts match snapshot

Run with:

    venv\\Scripts\\python.exe tests\\test_phase12c.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
import types
import uuid
from contextlib import contextmanager
from typing import Any, Callable, List, Tuple

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
# Fake OpenAI client — same shape as Phase 12B's helper, parameterized
# per-call so we can simulate retry-with-tighter-cap.
# ---------------------------------------------------------------------------

class _FakeChatCompletion:
    def __init__(self, content: str):
        self.choices = [
            types.SimpleNamespace(message=types.SimpleNamespace(content=content)),
        ]


class _FakeOpenAIClient:
    def __init__(self, scripted_responses):
        """scripted_responses: list of (content_str OR Exception). Returned
        in order. If the test consumes more calls than provided, the
        last entry is reused."""
        self.responses = list(scripted_responses)
        self.calls: List[dict] = []

        client_self = self

        class _Chat:
            class _Completions:
                @staticmethod
                def create(**kwargs):
                    client_self.calls.append(kwargs)
                    idx = min(
                        len(client_self.calls) - 1,
                        len(client_self.responses) - 1,
                    )
                    response = client_self.responses[idx]
                    if isinstance(response, Exception):
                        raise response
                    return _FakeChatCompletion(response)

            completions = _Completions()

        self.chat = _Chat()


def _make_composer(scripted_responses):
    """Returns (composer, client) — composer has its _client_factory
    patched to return the fake client."""
    from app.services.briefing.briefing_composer import BriefingComposer

    client = _FakeOpenAIClient(scripted_responses)
    composer = BriefingComposer()
    composer._client_factory = staticmethod(lambda: client)
    return composer, client


# Default LLM payload for the happy path.
_DEFAULT_LLM_RESPONSE = json.dumps({
    "summary_text": "The team discussed sprint progress and reviewed the API gateway migration plan.",
    "decisions_text": "Three decisions were made today. The authentication service will migrate first. The old gateway stays active until load testing passes. Production rollout is scheduled for September 20th.",
    "assigned_text": "Two action items were assigned. Ravi will prepare the migration document by September 15th. Sarah will run load tests by September 12th.",
    "unassigned_text": "I found two tasks without owners. Review fallback architecture. Update deployment documentation. Please assign owners before closing these items.",
})


# ---------------------------------------------------------------------------
# Seeding helpers — populate MeetingState with realistic shapes.
# ---------------------------------------------------------------------------

def _seed_state(meeting_id: str, *, decisions=None, tasks=None, summary=""):
    from app.services.meeting_memory.meeting_state_store import state_store
    from app.services.live_decisions.live_decision_models import LiveDecision
    from app.services.live_tasks.live_task_models import LiveTask

    state = state_store.get_state(meeting_id)
    # Wipe — get_state initializes if missing, but if a previous test
    # left state we want a clean slate.
    state.active_decisions = {}
    state.active_tasks = {}
    state.summary = summary

    for i, d in enumerate(decisions or []):
        decision = LiveDecision(
            id=f"dec-{i}",
            decision=d["decision"],
            fingerprint=f"fp-d-{i}",
            decided_by=d.get("decided_by"),
            decision_type=d.get("decision_type", "other"),
            status=d.get("status", "confirmed"),
            confidence=d.get("confidence", 0.9),
            source_speaker=d.get("source_speaker", "Alice"),
            source_transcript_chunk_id=1,
        )
        state.active_decisions[decision.fingerprint] = decision

    for i, t in enumerate(tasks or []):
        task = LiveTask(
            id=f"task-{i}",
            task=t["task"],
            fingerprint=f"fp-t-{i}",
            owner=t.get("owner"),
            ownership_type="explicit" if t.get("owner") else "unresolved",
            status="confirmed" if t.get("owner") else "detected",
            confidence=t.get("confidence", 0.9),
            source_speaker=t.get("source_speaker", "Alice"),
            source_transcript_chunk_id=1,
            deadline=t.get("deadline"),
        )
        state.active_tasks[task.fingerprint] = task

    return state


def _wipe_state(meeting_id: str):
    """Test cleanup — drop the meeting from the store entirely."""
    from app.services.meeting_memory.meeting_state_store import state_store
    state_store.remove_state(meeting_id)


# ---------------------------------------------------------------------------
# 12C.1 - Empty / sparse state
# ---------------------------------------------------------------------------

def test_empty_state_returns_none():
    mid = f"test-{uuid.uuid4()}"
    composer, client = _make_composer([_DEFAULT_LLM_RESPONSE])
    try:
        # Don't even touch the state store — first access creates empty state.
        result = composer.compose(meeting_id=mid)
        assert result is None
        # And critically: no LLM call wasted.
        assert len(client.calls) == 0, (
            "should not have called LLM for empty state"
        )
    finally:
        _wipe_state(mid)


def test_state_with_only_short_summary_returns_none():
    mid = f"test-{uuid.uuid4()}"
    _seed_state(mid, summary="brief talk")  # 2 words; below 4-word floor
    composer, client = _make_composer([_DEFAULT_LLM_RESPONSE])
    try:
        result = composer.compose(meeting_id=mid)
        assert result is None
        assert len(client.calls) == 0
    finally:
        _wipe_state(mid)


def test_state_with_only_meaningful_summary_composes():
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        summary="The team discussed sprint progress and API migration plans.",
    )
    composer, _ = _make_composer([_DEFAULT_LLM_RESPONSE])
    try:
        result = composer.compose(meeting_id=mid)
        assert result is not None
        assert "summary" in result.sections_included
    finally:
        _wipe_state(mid)


def test_state_with_one_decision_composes():
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[{"decision": "Migrate auth first", "decided_by": "Team"}],
    )
    composer, _ = _make_composer([_DEFAULT_LLM_RESPONSE])
    try:
        result = composer.compose(meeting_id=mid)
        assert result is not None
        assert "decisions" in result.sections_included
    finally:
        _wipe_state(mid)


# ---------------------------------------------------------------------------
# 12C.2 - Section assembly
# ---------------------------------------------------------------------------

def test_opening_and_closing_are_hardcoded():
    mid = f"test-{uuid.uuid4()}"
    _seed_state(mid, decisions=[{"decision": "X", "decided_by": "Y"}])
    # LLM tries to inject its own opening / closing — we ignore it.
    malicious = json.dumps({
        "summary_text": "The team discussed several items.",
        "decisions_text": "EVIL OPENING. One decision: X.",
        "assigned_text": "",
        "unassigned_text": "",
    })
    composer, _ = _make_composer([malicious])
    try:
        result = composer.compose(meeting_id=mid)
        assert result is not None
        assert result.opening_text == "Before we wrap up, here's a quick summary of today's discussion."
        assert result.closing_text == "Thank you everyone."
        assert result.full_text.startswith("Before we wrap up,")
        assert result.full_text.endswith("Thank you everyone.")
    finally:
        _wipe_state(mid)


def test_disabled_section_blanked_even_if_llm_returned_text():
    from app.schemas.briefing_schema import BriefingSections
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[{"decision": "X", "decided_by": "Y"}],
        tasks=[{"task": "A", "owner": "Bob"}],
    )
    composer, _ = _make_composer([_DEFAULT_LLM_RESPONSE])
    try:
        # Only emit opening + decisions + closing.
        enabled = (
            BriefingSections.OPENING
            | BriefingSections.DECISIONS
            | BriefingSections.CLOSING
        )
        result = composer.compose(meeting_id=mid, sections_enabled=enabled)
        assert result is not None
        assert result.summary_text is None
        assert result.assigned_text is None
        assert result.unassigned_text is None
        assert "summary" not in result.sections_included
        assert "assigned" not in result.sections_included
        assert "unassigned" not in result.sections_included
        assert "decisions" in result.sections_included
    finally:
        _wipe_state(mid)


def test_full_text_join_order():
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[{"decision": "X", "decided_by": "Y"}],
        tasks=[{"task": "A", "owner": "Bob"}, {"task": "B", "owner": None}],
    )
    # Markers must be long enough that the joined script clears MIN_SECONDS
    # (8s at 150 wpm = 20 words) — pad each section with filler words.
    pad = " filler word filler word filler word."
    response = json.dumps({
        "summary_text": "SUMMARY-MARKER" + pad,
        "decisions_text": "DECISIONS-MARKER" + pad,
        "assigned_text": "ASSIGNED-MARKER" + pad,
        "unassigned_text": "UNASSIGNED-MARKER" + pad,
    })
    composer, _ = _make_composer([response])
    try:
        result = composer.compose(meeting_id=mid)
        assert result is not None, "composer returned None"
        # Verify section order in full_text.
        text = result.full_text
        i_open = text.index("Before we wrap up")
        i_sum = text.index("SUMMARY-MARKER")
        i_dec = text.index("DECISIONS-MARKER")
        i_asg = text.index("ASSIGNED-MARKER")
        i_una = text.index("UNASSIGNED-MARKER")
        i_close = text.index("Thank you everyone")
        assert i_open < i_sum < i_dec < i_asg < i_una < i_close, (
            f"out of order: {text!r}"
        )
    finally:
        _wipe_state(mid)


# ---------------------------------------------------------------------------
# 12C.3 - Task routing + decision ordering
# ---------------------------------------------------------------------------

def test_tasks_routed_by_owner_presence():
    """Snapshot helper splits tasks into assigned/unassigned by owner."""
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        tasks=[
            {"task": "Has owner", "owner": "Alice"},
            {"task": "No owner", "owner": None},
            {"task": "Empty owner", "owner": ""},  # treat empty as unassigned
        ],
    )
    composer, _ = _make_composer([_DEFAULT_LLM_RESPONSE])
    try:
        snapshot = composer._snapshot_state(mid)
        assigned_texts = [t["task"] for t in snapshot["assigned_tasks"]]
        unassigned_texts = [t["task"] for t in snapshot["unassigned_tasks"]]
        assert "Has owner" in assigned_texts
        assert "No owner" in unassigned_texts
        assert "Empty owner" in unassigned_texts
        assert "Has owner" not in unassigned_texts
        assert "No owner" not in assigned_texts
    finally:
        _wipe_state(mid)


def test_sentinel_owners_route_to_unassigned():
    """Upstream Phase 11 sometimes puts type strings ('unassigned_task',
    'self_assigned_task') or synthetic group names ('Conversation Group')
    into LiveTask.owner. These are NOT real owners — they must route
    to the unassigned bucket and be reported as owner=None so the LLM
    doesn't speak them aloud ('The Conversation Group will...')."""
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        tasks=[
            {"task": "Real owner", "owner": "Alice"},
            {"task": "Sentinel A", "owner": "Conversation Group"},
            {"task": "Sentinel B", "owner": "unassigned_task"},
            {"task": "Sentinel C", "owner": "self_assigned_task"},
            {"task": "Sentinel D", "owner": "assigned_task"},
            {"task": "Sentinel E", "owner": "unknown"},
            {"task": "Sentinel F", "owner": "Unknown Speaker"},
        ],
    )
    composer, _ = _make_composer([_DEFAULT_LLM_RESPONSE])
    try:
        snapshot = composer._snapshot_state(mid)
        assigned_texts = [t["task"] for t in snapshot["assigned_tasks"]]
        unassigned_texts = [t["task"] for t in snapshot["unassigned_tasks"]]
        # Only the real owner survives to assigned.
        assert assigned_texts == ["Real owner"]
        # All sentinels routed to unassigned.
        for sentinel_task in [
            "Sentinel A", "Sentinel B", "Sentinel C",
            "Sentinel D", "Sentinel E", "Sentinel F",
        ]:
            assert sentinel_task in unassigned_texts, (
                f"{sentinel_task} should be unassigned"
            )
        # And the owner field in unassigned entries is normalized to None.
        for entry in snapshot["unassigned_tasks"]:
            assert entry["owner"] is None, (
                f"unassigned entry should have owner=None, got {entry['owner']!r}"
            )
    finally:
        _wipe_state(mid)


def test_sentinel_decided_by_normalized():
    """Same sentinel filter applies to LiveDecision.decided_by."""
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[
            {"decision": "Real call", "decided_by": "Alice"},
            {"decision": "Group call", "decided_by": "Conversation Group"},
        ],
    )
    composer, _ = _make_composer([_DEFAULT_LLM_RESPONSE])
    try:
        snapshot = composer._snapshot_state(mid)
        by_text = {d["decision"]: d["decided_by"] for d in snapshot["decisions"]}
        assert by_text["Real call"] == "Alice"
        assert by_text["Group call"] is None
    finally:
        _wipe_state(mid)


def test_decisions_sorted_by_confidence_descending():
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[
            {"decision": "Low conf", "decided_by": "A", "confidence": 0.55},
            {"decision": "High conf", "decided_by": "B", "confidence": 0.95},
            {"decision": "Mid conf", "decided_by": "C", "confidence": 0.75},
        ],
    )
    composer, _ = _make_composer([_DEFAULT_LLM_RESPONSE])
    try:
        snapshot = composer._snapshot_state(mid)
        ordered = [d["decision"] for d in snapshot["decisions"]]
        assert ordered == ["High conf", "Mid conf", "Low conf"], (
            f"unexpected order: {ordered}"
        )
    finally:
        _wipe_state(mid)


# ---------------------------------------------------------------------------
# 12C.4 - Length cap
# ---------------------------------------------------------------------------

def test_overshoot_triggers_retry_with_tighter_cap():
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[{"decision": "Migrate auth first", "decided_by": "Team"}],
    )

    # First response: WAY over budget — 500-word essay. Second: short.
    bloated = " ".join(["overflow"] * 500)
    bloated_response = json.dumps({
        "summary_text": bloated,
        "decisions_text": "",
        "assigned_text": "",
        "unassigned_text": "",
    })
    short_response = json.dumps({
        "summary_text": "Short summary fits.",
        "decisions_text": "One decision was made.",
        "assigned_text": "",
        "unassigned_text": "",
    })

    composer, client = _make_composer([bloated_response, short_response])
    try:
        result = composer.compose(meeting_id=mid, max_seconds=30)
        assert result is not None
        # Two LLM calls — initial + retry.
        assert len(client.calls) == 2, (
            f"expected 2 LLM calls (initial+retry), got {len(client.calls)}"
        )
        # Final script should be the short one.
        assert "Short summary fits" in result.full_text
        # And within the budget (30s * 150wpm / 60 = 75 words).
        assert result.word_count <= 75
    finally:
        _wipe_state(mid)


def test_too_short_brief_returns_none():
    """If the composed script ends up below MIN_SECONDS, skip it."""
    from app.config.settings import settings
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[{"decision": "X", "decided_by": "Y"}],
    )

    # LLM returns nothing usable — only opening + closing would remain,
    # which is ~12 words = ~5s, below the 8s floor.
    empty_response = json.dumps({
        "summary_text": "",
        "decisions_text": "",
        "assigned_text": "",
        "unassigned_text": "",
    })
    composer, _ = _make_composer([empty_response])
    try:
        result = composer.compose(meeting_id=mid)
        assert result is None, (
            "expected None when composed script falls below MIN_SECONDS"
        )
    finally:
        _wipe_state(mid)


# ---------------------------------------------------------------------------
# 12C.5 - Failure handling
# ---------------------------------------------------------------------------

def test_llm_exception_returns_none():
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[{"decision": "X", "decided_by": "Y"}],
    )
    composer, _ = _make_composer([RuntimeError("OpenAI 500")])
    try:
        result = composer.compose(meeting_id=mid)
        assert result is None
    finally:
        _wipe_state(mid)


def test_llm_invalid_json_returns_none():
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[{"decision": "X", "decided_by": "Y"}],
    )
    composer, _ = _make_composer(["not valid json {{"])
    try:
        result = composer.compose(meeting_id=mid)
        assert result is None
    finally:
        _wipe_state(mid)


def test_unknown_prompt_version_returns_none():
    from app.config import settings as settings_mod
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[{"decision": "X", "decided_by": "Y"}],
    )
    composer, client = _make_composer([_DEFAULT_LLM_RESPONSE])
    original_version = settings_mod.settings.CLOSING_BRIEFING_PROMPT_VERSION
    settings_mod.settings.CLOSING_BRIEFING_PROMPT_VERSION = "vNONEXISTENT"
    try:
        result = composer.compose(meeting_id=mid)
        assert result is None
        assert len(client.calls) == 0
    finally:
        settings_mod.settings.CLOSING_BRIEFING_PROMPT_VERSION = original_version
        _wipe_state(mid)


# ---------------------------------------------------------------------------
# 12C.6 - Audit / metadata
# ---------------------------------------------------------------------------

def test_audit_metadata_populated():
    from app.config.settings import settings
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[
            {"decision": "X", "decided_by": "Y", "confidence": 0.9},
            {"decision": "Z", "decided_by": "W", "confidence": 0.7},
        ],
        tasks=[
            {"task": "T1", "owner": "A"},
            {"task": "T2", "owner": None},
            {"task": "T3", "owner": None},
        ],
        summary="The team made solid progress on three different fronts today.",
    )
    composer, _ = _make_composer([_DEFAULT_LLM_RESPONSE])
    try:
        result = composer.compose(meeting_id=mid)
        assert result is not None
        assert result.model_used == settings.CLOSING_BRIEFING_MODEL
        assert result.prompt_version == settings.CLOSING_BRIEFING_PROMPT_VERSION
        s = result.source_state_summary
        assert s["decisions_count"] == 2
        assert s["assigned_count"] == 1
        assert s["unassigned_count"] == 2
        assert s["summary_word_count"] == 10  # 10 words in seeded summary
    finally:
        _wipe_state(mid)


def test_estimated_seconds_derives_from_wpm():
    from app.config.settings import settings
    mid = f"test-{uuid.uuid4()}"
    _seed_state(
        mid,
        decisions=[{"decision": "X", "decided_by": "Y"}],
    )
    composer, _ = _make_composer([_DEFAULT_LLM_RESPONSE])
    try:
        result = composer.compose(meeting_id=mid)
        assert result is not None
        expected = result.word_count * 60.0 / settings.CLOSING_BRIEFING_WPM
        assert abs(result.estimated_seconds - expected) < 0.01
    finally:
        _wipe_state(mid)


# ---------------------------------------------------------------------------
# 12C.7 - Skill registration
# ---------------------------------------------------------------------------

def test_skill_descriptor_registered():
    # Ensure the skill module was imported (it registers on import).
    import app.skills  # noqa: F401
    from app.skills.registry import SkillRegistry
    skill = SkillRegistry.get("closing_briefing")
    assert skill is not None, "closing_briefing skill should be registered"
    assert skill.enabled_by_default is False, (
        "closing_briefing must be opt-in"
    )
    assert "Closing Briefing" in skill.capabilities


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    suites = [
        ("12C.1 sparse state", [
            ("empty state returns None", test_empty_state_returns_none),
            ("short summary alone returns None", test_state_with_only_short_summary_returns_none),
            ("meaningful summary alone composes", test_state_with_only_meaningful_summary_composes),
            ("one decision composes", test_state_with_one_decision_composes),
        ]),
        ("12C.2 section assembly", [
            ("opening + closing hardcoded", test_opening_and_closing_are_hardcoded),
            ("disabled section blanked", test_disabled_section_blanked_even_if_llm_returned_text),
            ("full_text join order", test_full_text_join_order),
        ]),
        ("12C.3 task routing", [
            ("tasks routed by owner presence", test_tasks_routed_by_owner_presence),
            ("sentinel owners route to unassigned", test_sentinel_owners_route_to_unassigned),
            ("sentinel decided_by normalized", test_sentinel_decided_by_normalized),
            ("decisions sorted by confidence desc", test_decisions_sorted_by_confidence_descending),
        ]),
        ("12C.4 length cap", [
            ("overshoot triggers retry", test_overshoot_triggers_retry_with_tighter_cap),
            ("too-short brief returns None", test_too_short_brief_returns_none),
        ]),
        ("12C.5 failure handling", [
            ("LLM exception returns None", test_llm_exception_returns_none),
            ("LLM invalid JSON returns None", test_llm_invalid_json_returns_none),
            ("unknown prompt version returns None", test_unknown_prompt_version_returns_none),
        ]),
        ("12C.6 audit metadata", [
            ("metadata populated", test_audit_metadata_populated),
            ("estimated_seconds derives from WPM", test_estimated_seconds_derives_from_wpm),
        ]),
        ("12C.7 skill registration", [
            ("skill descriptor registered", test_skill_descriptor_registered),
        ]),
    ]

    for label, cases in suites:
        with section(label):
            for name, fn in cases:
                check(label.split()[0], name, fn)

    print()
    print("=== Phase 12C summary ===")
    passes = sum(1 for r in results if r[2] == "PASS")
    fails = sum(1 for r in results if r[2] == "FAIL")
    print(f"  PASS: {passes}")
    print(f"  FAIL: {fails}")
    print(f"  total: {len(results)}")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
