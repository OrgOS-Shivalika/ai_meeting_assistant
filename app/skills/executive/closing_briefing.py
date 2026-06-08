"""Phase 12C — Closing briefing skill descriptor.

Registers the skill in the global `SkillRegistry` for discoverability,
governance gating (Phase 11), and future eval integration. The actual
execution lives in `app/services/briefing/briefing_composer.py` —
this descriptor is metadata only.

Why a descriptor when the composer doesn't go through SkillExecutor:
- The SkillExecutor is designed for "ingest full transcript -> emit
  structured JSON" flows. The closing brief is "read live in-memory
  MeetingState -> emit spoken script" — a tight different shape.
- But registering keeps the skill visible to /agents/types catalog,
  the behavior-profile resolver, and any future eval harness, so
  admins can see it exists and reason about it the same way they
  reason about meetings/summaries.py.
"""
from app.skills.base import SkillDefinition
from app.skills.registry import register_skill


skill = SkillDefinition(
    id="closing_briefing",
    name="Closing Meeting Briefing",
    description=(
        "Produces a short spoken recap (~60s) of a meeting's summary, "
        "decisions, and action items. Spoken aloud by the meeting bot "
        "before it leaves the call."
    ),
    capabilities=["Closing Briefing", "Summaries"],
    system_prompt=(
        "You are an AI meeting participant. After watching a meeting, "
        "you deliver a short verbal recap that humans hear over the "
        "meeting audio channel — not a written report."
    ),
    # No retrieval — the composer reads live MeetingState directly.
    retrieval_config={"top_k": 0},
    # No persistent memory writes from the skill itself; the Phase 12D
    # orchestrator handles audit-table writes.
    memory_config={"read_from_memory": False, "write_to_memory": False},
    required_tools=[],
    emits_events=["meeting.closing_brief_composed"],
    # Default OFF — orgs must opt in via behavior config (Phase 12E).
    # Composing is harmless without speaking, but the spec says this
    # is an opt-in feature.
    enabled_by_default=False,
)

register_skill(skill)
