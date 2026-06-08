"""Phase 12C — Closing briefing composer.

Reads `MeetingState` (populated by Phase 11 live tasks + Phase 12B live
decisions + summary) and turns it into a typed `BriefingScript` ready
for TTS. One LLM call per composition. Hardcodes the opening + closing
templates so they're never affected by LLM drift.

Public API:

    composer = BriefingComposer()
    script = composer.compose(
        meeting_id="42",
        max_seconds=60,
        sections_enabled=ALL_SECTIONS,
    )
    if script:
        send_to_tts(script.full_text)
    else:
        # State was too sparse — no meaningful brief possible.
        mark_meeting_skipped()

Design choices
--------------
- ONE LLM call, all four LLM-authored sections in one shot. Trades
  off finer-grained retry control for ~3x lower latency and better
  stylistic consistency across sections.
- Hardcoded opening ("Before we wrap up, here's a quick summary of
  today's discussion.") and closing ("Thank you everyone.") — these
  shouldn't ever vary.
- The LLM call uses `response_format={"type": "json_object"}` so we
  get clean JSON, but the prompt also defines a strict schema (see
  `closing_briefing_prompt.PROMPT_V1`).
- Failure modes:
  * State empty / below MIN_SECONDS         -> return None
  * LLM call raises                          -> return None (caller marks failed)
  * LLM returns invalid JSON                 -> return None
  * LLM returns all-empty sections           -> return None
  * Length overshoot                         -> single retry with stricter cap
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.ai_agents.openAI_transcript_analyzer import _get_client
from app.ai_agents.prompts.closing_briefing_prompt import VERSIONS as PROMPT_VERSIONS
from app.config.settings import settings
from app.schemas.briefing_schema import (
    ALL_SECTIONS,
    BriefingScript,
    BriefingSections,
    LLMBriefingPayload,
)
from app.services.meeting_memory.meeting_state_store import state_store

logger = logging.getLogger(__name__)


# Hardcoded sentence templates. Kept here (not in the prompt module)
# because they are NOT LLM input — they're attached after composition.
# Single source of truth for spoken framing.
_OPENING_TEMPLATE = (
    "Before we wrap up, here's a quick summary of today's discussion."
)
_CLOSING_TEMPLATE = "Thank you everyone."


# Sentinel "owner" values that leak from upstream Phase 11 code into
# LiveTask.owner / LiveDecision.decided_by. They're NOT real owners and
# must be treated as None to prevent the LLM from speaking them aloud
# ("The Conversation Group will finalize...", "self_assigned_task will...").
# This is a defensive filter — upstream cleanup of these sentinels in
# TaskExtractor + StreamSession is a separate (and welcome) follow-up.
#
# Sources of leakage:
#   - "Conversation Group"   ← StreamSession.flush_thought_buffer's merged
#                              speaker_name; bleeds into TaskExtractor.
#   - "unassigned_task"      ← TaskExtractor LLM confusing `type` for `owner`
#   - "self_assigned_task"   ← same
#   - "assigned_task"        ← same
_OWNER_SENTINELS = frozenset({
    "Conversation Group",
    "unassigned_task",
    "self_assigned_task",
    "assigned_task",
    "unknown",
    "Unknown Speaker",
})


def _clean_owner(raw: Optional[str]) -> Optional[str]:
    """Return None for sentinel / placeholder owners; otherwise the
    stripped real name."""
    if not raw:
        return None
    name = raw.strip()
    if not name or name in _OWNER_SENTINELS:
        return None
    return name


class BriefingComposer:
    """Composes a `BriefingScript` from a meeting's live cognition state."""

    # Lazy LLM client factory — same pattern as the live extractors so
    # tests can swap without monkeypatching internals.
    _client_factory = staticmethod(_get_client)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def compose(
        self,
        meeting_id: str,
        max_seconds: int = None,
        sections_enabled: BriefingSections = ALL_SECTIONS,
    ) -> Optional[BriefingScript]:
        """Build the script. Returns None when state is too sparse OR
        the LLM call fails — caller (Phase 12D orchestrator) decides
        whether to retry / mark skipped / mark failed.
        """
        max_seconds = max_seconds or settings.CLOSING_BRIEFING_MAX_SECONDS
        min_seconds = settings.CLOSING_BRIEFING_MIN_SECONDS
        wpm = settings.CLOSING_BRIEFING_WPM
        max_words = max(1, int(max_seconds * wpm / 60))
        # Reserve ~12 words for hardcoded opening + closing so the LLM
        # has the remaining budget. Floor at 30 words so even very
        # short ceilings still get some content.
        hardcoded_words = (
            (len(_OPENING_TEMPLATE.split()) if BriefingSections.OPENING in sections_enabled else 0)
            + (len(_CLOSING_TEMPLATE.split()) if BriefingSections.CLOSING in sections_enabled else 0)
        )
        llm_max_words = max(30, max_words - hardcoded_words)

        # 1. Snapshot the live state. Reads only — never mutates.
        snapshot = self._snapshot_state(meeting_id)
        if snapshot is None:
            logger.info(f"[BRIEFING] meeting={meeting_id} no state in store; skipping")
            return None

        if not self._has_minimum_signal(snapshot):
            logger.info(
                f"[BRIEFING] meeting={meeting_id} state too sparse "
                f"(decisions={len(snapshot['decisions'])}, "
                f"assigned={len(snapshot['assigned_tasks'])}, "
                f"unassigned={len(snapshot['unassigned_tasks'])}, "
                f"summary={'yes' if snapshot['summary'] else 'no'}); skipping"
            )
            return None

        # 2. Build the prompt for the configured version.
        prompt_version = settings.CLOSING_BRIEFING_PROMPT_VERSION
        render = PROMPT_VERSIONS.get(prompt_version)
        if render is None:
            logger.error(
                f"[BRIEFING] unknown prompt version {prompt_version!r}; "
                f"available: {list(PROMPT_VERSIONS.keys())}"
            )
            return None

        prompt_text = render(
            max_words=llm_max_words,
            summary=snapshot["summary"],
            decisions=snapshot["decisions"],
            assigned_tasks=snapshot["assigned_tasks"],
            unassigned_tasks=snapshot["unassigned_tasks"],
        )

        # 3. One LLM call. Retry once with a tighter cap if it overshoots.
        payload = self._call_llm(prompt_text)
        if payload is None:
            return None

        payload = self._enforce_section_toggles(payload, sections_enabled)

        script = self._assemble_script(
            meeting_id=meeting_id,
            payload=payload,
            sections_enabled=sections_enabled,
            prompt_version=prompt_version,
            snapshot=snapshot,
        )

        # 4. Length cap. Soft enforcement: if we overshoot, retry once
        # with a stricter ceiling. Don't loop forever.
        if script.word_count > max_words:
            tighter_words = max(20, int(max_words * 0.75))
            logger.info(
                f"[BRIEFING] meeting={meeting_id} overshoot "
                f"({script.word_count}/{max_words}w); retrying at {tighter_words}w"
            )
            retry_prompt = render(
                max_words=tighter_words,
                summary=snapshot["summary"],
                decisions=snapshot["decisions"],
                assigned_tasks=snapshot["assigned_tasks"],
                unassigned_tasks=snapshot["unassigned_tasks"],
            )
            retry_payload = self._call_llm(retry_prompt)
            if retry_payload is not None:
                retry_payload = self._enforce_section_toggles(retry_payload, sections_enabled)
                retry_script = self._assemble_script(
                    meeting_id=meeting_id,
                    payload=retry_payload,
                    sections_enabled=sections_enabled,
                    prompt_version=prompt_version,
                    snapshot=snapshot,
                )
                if retry_script.word_count <= max_words:
                    script = retry_script

        # 5. Floor — too-short briefings aren't worth speaking.
        if script.estimated_seconds < min_seconds:
            logger.info(
                f"[BRIEFING] meeting={meeting_id} composed brief too short "
                f"({script.estimated_seconds:.1f}s < {min_seconds}s); skipping"
            )
            return None

        return script

    # ------------------------------------------------------------------
    # State snapshot — pulls just what the composer needs from the live
    # store. Splits tasks into assigned / unassigned buckets here so the
    # prompt module stays simple.
    # ------------------------------------------------------------------

    def _snapshot_state(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        # The state_store creates a fresh empty state on first access.
        # We don't want to fabricate a brief from a never-active meeting,
        # so detect this by checking if anything has been written.
        state = state_store.get_state(meeting_id)

        decisions: List[Dict[str, Any]] = []
        for d in state.active_decisions.values():
            if not d.is_active:
                continue
            decisions.append({
                "decision": d.decision,
                "decided_by": _clean_owner(d.decided_by),
                "status": d.status,
                "confidence": d.confidence,
            })
        # Sort so high-confidence first — keeps the most certain decisions
        # at the top in case the LLM truncates.
        decisions.sort(key=lambda r: r.get("confidence", 0), reverse=True)

        assigned: List[Dict[str, Any]] = []
        unassigned: List[Dict[str, Any]] = []
        for t in state.active_tasks.values():
            if not t.is_active:
                continue
            # Sanitize the owner BEFORE deciding which bucket. Upstream
            # sometimes puts type strings ("unassigned_task") or
            # synthetic group names ("Conversation Group") in
            # LiveTask.owner — those must route to unassigned.
            real_owner = _clean_owner(t.owner)
            entry = {
                "task": t.task,
                "owner": real_owner,
                "deadline": t.deadline,
                "confidence": t.confidence,
                "status": t.status,
            }
            if real_owner:
                assigned.append(entry)
            else:
                unassigned.append(entry)
        assigned.sort(key=lambda r: r.get("confidence", 0), reverse=True)
        unassigned.sort(key=lambda r: r.get("confidence", 0), reverse=True)

        return {
            "meeting_id": meeting_id,
            "summary": state.summary or "",
            "decisions": decisions,
            "assigned_tasks": assigned,
            "unassigned_tasks": unassigned,
        }

    def _has_minimum_signal(self, snapshot: Dict[str, Any]) -> bool:
        """Returns False when state is so sparse the brief would be
        boilerplate-only. Floor: at least one of (decisions, tasks,
        meaningful summary)."""
        if snapshot["decisions"]:
            return True
        if snapshot["assigned_tasks"]:
            return True
        if snapshot["unassigned_tasks"]:
            return True
        # A non-empty summary alone is enough — the user said "what
        # happened?" is one of the four core questions.
        if snapshot["summary"] and len(snapshot["summary"].split()) >= 4:
            return True
        return False

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _call_llm(self, prompt_text: str) -> Optional[LLMBriefingPayload]:
        model = settings.CLOSING_BRIEFING_MODEL
        try:
            client = self._client_factory()
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You produce spoken meeting briefings for "
                            "text-to-speech engines. You always respond "
                            "with valid JSON matching the schema in the "
                            "user prompt. No prose, no markdown, no preamble."
                        ),
                    },
                    {"role": "user", "content": prompt_text},
                ],
                response_format={"type": "json_object"},
                timeout=15,
            )
            content = (response.choices[0].message.content or "{}").strip()
            data = json.loads(content)
            return LLMBriefingPayload.model_validate(data)
        except Exception as exc:
            logger.error(f"[BRIEFING] LLM call failed: {exc}", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def _enforce_section_toggles(
        self, payload: LLMBriefingPayload, sections_enabled: BriefingSections,
    ) -> LLMBriefingPayload:
        """If the caller disabled a section, blank it out even if the
        LLM produced text for it. (The prompt also tells the LLM to
        omit disabled sections, but defense-in-depth.)"""
        if BriefingSections.SUMMARY not in sections_enabled:
            payload.summary_text = ""
        if BriefingSections.DECISIONS not in sections_enabled:
            payload.decisions_text = ""
        if BriefingSections.ASSIGNED not in sections_enabled:
            payload.assigned_text = ""
        if BriefingSections.UNASSIGNED not in sections_enabled:
            payload.unassigned_text = ""
        return payload

    def _assemble_script(
        self,
        *,
        meeting_id: str,
        payload: LLMBriefingPayload,
        sections_enabled: BriefingSections,
        prompt_version: str,
        snapshot: Dict[str, Any],
    ) -> BriefingScript:
        opening = _OPENING_TEMPLATE if BriefingSections.OPENING in sections_enabled else None
        closing = _CLOSING_TEMPLATE if BriefingSections.CLOSING in sections_enabled else None

        # Helper — treat empty / whitespace as omitted.
        def _opt(s: str) -> Optional[str]:
            s = (s or "").strip()
            return s if s else None

        summary = _opt(payload.summary_text)
        decisions = _opt(payload.decisions_text)
        assigned = _opt(payload.assigned_text)
        unassigned = _opt(payload.unassigned_text)

        # Build full_text by joining non-empty sections in spoken order.
        parts: List[str] = []
        sections_included: List[str] = []
        if opening:
            parts.append(opening)
            sections_included.append("opening")
        if summary:
            parts.append(summary)
            sections_included.append("summary")
        if decisions:
            parts.append(decisions)
            sections_included.append("decisions")
        if assigned:
            parts.append(assigned)
            sections_included.append("assigned")
        if unassigned:
            parts.append(unassigned)
            sections_included.append("unassigned")
        if closing:
            parts.append(closing)
            sections_included.append("closing")

        # Single space between sections — TTS handles inter-sentence
        # pacing better than explicit newlines do.
        full_text = " ".join(parts).strip()
        word_count = len(full_text.split())
        estimated_seconds = word_count * 60.0 / settings.CLOSING_BRIEFING_WPM

        return BriefingScript(
            meeting_id=meeting_id,
            opening_text=opening,
            closing_text=closing,
            summary_text=summary,
            decisions_text=decisions,
            assigned_text=assigned,
            unassigned_text=unassigned,
            full_text=full_text,
            word_count=word_count,
            estimated_seconds=estimated_seconds,
            sections_included=sections_included,
            model_used=settings.CLOSING_BRIEFING_MODEL,
            prompt_version=prompt_version,
            source_state_summary={
                "decisions_count": len(snapshot["decisions"]),
                "assigned_count": len(snapshot["assigned_tasks"]),
                "unassigned_count": len(snapshot["unassigned_tasks"]),
                "summary_word_count": len((snapshot["summary"] or "").split()),
            },
        )
