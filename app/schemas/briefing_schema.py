"""Phase 12C — Closing briefing schemas.

Pydantic models for the briefing composer's input + output. The
`BriefingScript` is the canonical artifact passed from 12C to 12D
(TTS + Recall audio injection).

Section ownership
-----------------
- `opening_text` / `closing_text` — HARDCODED templates the composer
  attaches. Never authored by the LLM. Keeping them out of the LLM
  call shaves ~10 words off the budget and guarantees consistent
  framing across briefings.
- `summary_text` / `decisions_text` / `assigned_text` / `unassigned_text`
  — LLM-authored. Each may be None if the corresponding section was
  omitted (either disabled by behavior config or no source data).
- `full_text` — joined concatenation. This is what TTS consumes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional
from enum import Flag, auto

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Section enable bitfield. Phase 12E (behavior config) reads workspace
# overrides into one of these; defaults to ALL.
# ---------------------------------------------------------------------------

class BriefingSections(Flag):
    OPENING = auto()
    SUMMARY = auto()
    DECISIONS = auto()
    ASSIGNED = auto()
    UNASSIGNED = auto()
    CLOSING = auto()


ALL_SECTIONS = (
    BriefingSections.OPENING
    | BriefingSections.SUMMARY
    | BriefingSections.DECISIONS
    | BriefingSections.ASSIGNED
    | BriefingSections.UNASSIGNED
    | BriefingSections.CLOSING
)


# ---------------------------------------------------------------------------
# Composer input — the snapshot Phase 12D will pass at end-of-meeting.
# Wrapped in a model so the call site is grep-able and future params
# (voice, persona, language) can land here without a sig change.
# ---------------------------------------------------------------------------

class BriefingComposeRequest(BaseModel):
    meeting_id: str
    max_seconds: int = Field(default=60, ge=10, le=300)
    sections_enabled: int = Field(
        default=int(ALL_SECTIONS.value),
        description="Bitfield of BriefingSections; defaults to ALL.",
    )

    # Phase 12D will pass the resolved BehaviorProfile here; in 12C the
    # composer ignores it. Reserved slot.
    behavior_context: Optional[dict] = None


# ---------------------------------------------------------------------------
# LLM-authored output. The composer post-processes this into the final
# BriefingScript (attaches hardcoded opening/closing, computes word
# count + duration, joins full_text).
# ---------------------------------------------------------------------------

class LLMBriefingPayload(BaseModel):
    """Strict JSON shape the prompt asks for. Any field may be empty
    string when the LLM determined the section should be omitted."""
    summary_text: str = ""
    decisions_text: str = ""
    assigned_text: str = ""
    unassigned_text: str = ""


# ---------------------------------------------------------------------------
# Final composed script. This is what 12D's TTS / orchestrator consumes.
# ---------------------------------------------------------------------------

class BriefingScript(BaseModel):
    """A composed, ready-to-speak briefing.

    Field naming choices
    --------------------
    - All `*_text` fields are Optional[str], None when the section is
      omitted. Empty string means "LLM tried but produced nothing usable"
      and is treated as omitted at full_text join time.
    - `estimated_seconds` is a float (not int) so the orchestrator can
      decide whether to retry-with-shorter rather than just truncate.
    - `prompt_version` + `model_used` flow into the Phase 12D audit table.
    """
    model_config = ConfigDict(from_attributes=True)

    meeting_id: str

    # Hardcoded sections (composer-attached, not LLM)
    opening_text: Optional[str] = None
    closing_text: Optional[str] = None

    # LLM-authored sections
    summary_text: Optional[str] = None
    decisions_text: Optional[str] = None
    assigned_text: Optional[str] = None
    unassigned_text: Optional[str] = None

    # Derived
    full_text: str
    word_count: int
    estimated_seconds: float
    sections_included: List[
        Literal["opening", "summary", "decisions", "assigned", "unassigned", "closing"]
    ] = Field(default_factory=list)

    # Audit metadata (Phase 12D writes these to closing_briefings)
    model_used: str
    prompt_version: str
    composed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    # Snapshot of what fed the LLM — useful for replay / debugging.
    # Not the FULL MeetingState (that's expensive); just counts.
    source_state_summary: dict = Field(default_factory=dict)
