"""
Tests for the v2 closing-briefing prompt + composer changes that surface
dateless tasks to the bot.

Covers:
  - VERSIONS registry exposes v1 and v2; v2 is callable
  - v2 formatter: assigned line wrapping for phrase / ISO / none
  - v2 formatter: unassigned line wrapping for phrase / ISO / none
  - v2 prompt instructs the LLM on the (no date) sentinel
  - Composer snapshot carries `due_date` and `has_date` per entry
"""
from unittest.mock import patch

import pytest

from app.ai_agents.prompts import closing_briefing_prompt as briefing_prompt
from app.services.briefing.briefing_composer import BriefingComposer
from app.services.live_tasks.live_task_models import LiveTask
from app.services.meeting_memory.meeting_state_store import state_store


# ---------------------------------------------------------------------------
# Versions registry
# ---------------------------------------------------------------------------


def test_versions_registry_includes_v1_and_v2():
    assert "v1" in briefing_prompt.VERSIONS
    assert "v2" in briefing_prompt.VERSIONS
    assert callable(briefing_prompt.VERSIONS["v2"])


def test_v2_render_returns_non_empty_string():
    out = briefing_prompt.render_v2(
        max_words=120, summary="", decisions=[],
        assigned_tasks=[], unassigned_tasks=[],
    )
    assert isinstance(out, str) and len(out) > 200


# ---------------------------------------------------------------------------
# v2 formatter — assigned tasks
# ---------------------------------------------------------------------------


def _render_with(assigned=None, unassigned=None):
    return briefing_prompt.render_v2(
        max_words=200,
        summary="A short meeting summary about the migration.",
        decisions=[],
        assigned_tasks=assigned or [],
        unassigned_tasks=unassigned or [],
        target_language="english",
    )


def test_assigned_phrase_does_not_double_prepend_by():
    """deadline='by Friday' must NOT render as 'by by Friday'."""
    out = _render_with(assigned=[
        {"task": "ship the build", "owner": "Sarah",
         "deadline": "by Friday", "due_date": "2026-06-13"},
    ])
    assert "- Sarah will ship the build (by Friday)" in out
    assert "by by" not in out


def test_assigned_iso_only_prepends_by():
    """ISO date with no phrase gets a leading 'by'."""
    out = _render_with(assigned=[
        {"task": "fix the bug", "owner": "Ravi",
         "deadline": None, "due_date": "2026-06-15"},
    ])
    assert "- Ravi will fix the bug (by 2026-06-15)" in out


def test_assigned_dateless_uses_no_date_sentinel():
    """No phrase AND no ISO → `(no date)` literal sentinel."""
    out = _render_with(assigned=[
        {"task": "review the docs", "owner": "Priya",
         "deadline": None, "due_date": None},
    ])
    assert "- Priya will review the docs (no date)" in out


def test_assigned_natural_phrase_without_by_is_preserved():
    """deadline='tomorrow' is the speaker's word — preserved verbatim."""
    out = _render_with(assigned=[
        {"task": "deploy", "owner": "Amit",
         "deadline": "tomorrow", "due_date": "2026-06-12"},
    ])
    assert "- Amit will deploy (tomorrow)" in out


# ---------------------------------------------------------------------------
# v2 formatter — unassigned tasks
# ---------------------------------------------------------------------------


def test_unassigned_phrase_uses_phrase():
    out = _render_with(unassigned=[
        {"task": "update onboarding doc",
         "deadline": "by Monday", "due_date": "2026-06-16"},
    ])
    assert "- update onboarding doc (by Monday)" in out


def test_unassigned_iso_only_prepends_by():
    out = _render_with(unassigned=[
        {"task": "audit the API contracts",
         "deadline": None, "due_date": "2026-06-20"},
    ])
    assert "- audit the API contracts (by 2026-06-20)" in out


def test_unassigned_dateless_uses_no_date_sentinel():
    """The case the user explicitly called out:
    'tasks which don't have any owner and dates'."""
    out = _render_with(unassigned=[
        {"task": "review the migration script",
         "deadline": None, "due_date": None},
    ])
    assert "- review the migration script (no date)" in out


# ---------------------------------------------------------------------------
# v2 prompt instructions — sentinels are explained, LLM is told to speak
# both flavours and to translate (no date) into the right per-language
# phrasing.
# ---------------------------------------------------------------------------


def test_v2_prompt_warns_against_reading_sentinels_aloud():
    out = _render_with()
    assert "NEVER read input sentinels aloud" in out
    assert "(no date)" in out


def test_v2_prompt_demands_speaking_every_assigned_task():
    out = _render_with()
    assert "Speak EVERY assigned task" in out


def test_v2_prompt_distinguishes_unassigned_flavours():
    out = _render_with()
    # The prompt must reference BOTH (no owner / has date)
    # AND (no owner / no date) to teach the LLM the difference.
    assert "no owner, but a deadline IS present" in out
    assert "no owner AND no deadline" in out


def test_v2_prompt_includes_owner_and_dates_nudge():
    out = _render_with()
    # The closing nudge should mention BOTH owners and dates so the
    # listener knows what's missing.
    assert "assign owners and dates" in out


# ---------------------------------------------------------------------------
# Composer snapshot — propagates due_date + has_date through
# ---------------------------------------------------------------------------


def test_composer_snapshot_carries_due_date_and_has_date():
    """The composer must thread `due_date` and `has_date` through to
    the prompt input so v2's formatter can choose the right shape per
    task."""
    meeting_id = "test_dateless_briefing_1"
    state = state_store.get_state(meeting_id)
    state.active_tasks.clear()
    try:
        # Task A: has owner, has both deadline + ISO
        a = LiveTask(
            id="a", task="ship the build", fingerprint="fa",
            owner="Sarah", ownership_type="explicit",
            status="confirmed", confidence=0.9,
            source_speaker="Sarah", source_transcript_chunk_id=1,
            deadline="by Friday", due_date="2026-06-13",
        )
        # Task B: has owner, NO date at all
        b = LiveTask(
            id="b", task="review the API docs", fingerprint="fb",
            owner="Priya", ownership_type="explicit",
            status="confirmed", confidence=0.85,
            source_speaker="Priya", source_transcript_chunk_id=2,
        )
        # Task C: NO owner, has ISO date only
        c = LiveTask(
            id="c", task="audit the contracts", fingerprint="fc",
            ownership_type="unresolved",
            status="detected", confidence=0.7,
            source_speaker="someone", source_transcript_chunk_id=3,
            due_date="2026-06-20",
        )
        # Task D: NO owner, NO date — the user's call-out case
        d = LiveTask(
            id="d", task="finalize the rollout plan", fingerprint="fd",
            ownership_type="unresolved",
            status="detected", confidence=0.7,
            source_speaker="someone", source_transcript_chunk_id=4,
        )
        for t in (a, b, c, d):
            state.active_tasks[t.fingerprint] = t

        composer = BriefingComposer()
        snap = composer._snapshot_state(meeting_id)

        # Routing: A + B in assigned, C + D in unassigned.
        assert len(snap["assigned_tasks"]) == 2
        assert len(snap["unassigned_tasks"]) == 2

        by_task = {e["task"]: e for e in snap["assigned_tasks"] + snap["unassigned_tasks"]}

        # has_date flag is correct per entry
        assert by_task["ship the build"]["has_date"] is True
        assert by_task["review the API docs"]["has_date"] is False
        assert by_task["audit the contracts"]["has_date"] is True
        assert by_task["finalize the rollout plan"]["has_date"] is False

        # due_date is plumbed (ISO or None)
        assert by_task["ship the build"]["due_date"] == "2026-06-13"
        assert by_task["review the API docs"]["due_date"] is None
        assert by_task["audit the contracts"]["due_date"] == "2026-06-20"
        assert by_task["finalize the rollout plan"]["due_date"] is None
    finally:
        state_store.remove_state(meeting_id)


# ---------------------------------------------------------------------------
# End-to-end: snapshot → v2 render produces the right ground-truth lines
# ---------------------------------------------------------------------------


def test_snapshot_feeds_v2_render_with_correct_shapes():
    meeting_id = "test_dateless_briefing_2"
    state = state_store.get_state(meeting_id)
    state.active_tasks.clear()
    try:
        state.active_tasks["fa"] = LiveTask(
            id="a", task="ship the build", fingerprint="fa",
            owner="Sarah", ownership_type="explicit",
            status="confirmed", confidence=0.9,
            source_speaker="Sarah", source_transcript_chunk_id=1,
            deadline="by Friday", due_date="2026-06-13",
        )
        state.active_tasks["fb"] = LiveTask(
            id="b", task="review the docs", fingerprint="fb",
            owner="Priya", ownership_type="explicit",
            status="confirmed", confidence=0.85,
            source_speaker="Priya", source_transcript_chunk_id=2,
        )
        state.active_tasks["fc"] = LiveTask(
            id="c", task="finalize the plan", fingerprint="fc",
            ownership_type="unresolved",
            status="detected", confidence=0.7,
            source_speaker="someone", source_transcript_chunk_id=3,
        )

        composer = BriefingComposer()
        snap = composer._snapshot_state(meeting_id)
        rendered = briefing_prompt.render_v2(
            max_words=200,
            summary=snap["summary"],
            decisions=snap["decisions"],
            assigned_tasks=snap["assigned_tasks"],
            unassigned_tasks=snap["unassigned_tasks"],
            target_language="english",
        )

        # All three task shapes appear in the rendered prompt:
        assert "- Sarah will ship the build (by Friday)" in rendered
        assert "- Priya will review the docs (no date)" in rendered
        assert "- finalize the plan (no date)" in rendered
    finally:
        state_store.remove_state(meeting_id)
