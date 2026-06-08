"""Phase 12B — Live summary tracker.

Maintains a rolling 2-3 sentence summary of the meeting in
`MeetingState.summary`. Designed for low LLM cost (one call every
N semantic batches, not per chunk) and stylistic stability (the new
summary is fed the previous summary so it evolves smoothly rather
than rewriting from scratch).

Cadence
-------
- Updates every `_SUMMARY_BATCH_INTERVAL` semantic batches by default
  (currently 3 — typical batch ~60 words ≈ 30s of speech, so ~90s
  between updates). The class also exposes `force=True` for the
  end-of-meeting trigger so the briefing composer always reads a
  fresh-enough summary.
- The cadence counter lives on `MeetingState` (Phase 12B added
  `summary_batches_since_update`) — surviving across detector calls
  without a separate registry.

LLM contract
------------
- Prompt instructs strict ≤3 sentence output.
- Empty/whitespace responses are dropped (we keep the previous summary).
- Failures fall through silently — the previous summary is preserved,
  so summary corruption is impossible. The briefing composer will use
  whatever's there (or empty string if no batches have completed yet).

Why not piggyback on TaskExtractor / DecisionExtractor
------------------------------------------------------
Both of those are aggressive single-pass extractors. A rolling summary
needs the PREVIOUS summary as input AND must produce a single coherent
paragraph (not a list). The interface mismatch is too large to share —
this is a sibling, not a subclass.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.ai_agents.openAI_transcript_analyzer import _get_client
from app.services.meeting_memory.meeting_state_store import MeetingState

logger = logging.getLogger(__name__)

# Tunables — module-level so tests can override without touching the
# class internals.
_SUMMARY_BATCH_INTERVAL = 3   # Update every Nth batch
_SUMMARY_MAX_SENTENCES = 3
_SUMMARY_MODEL = "gpt-4o-mini"
_SUMMARY_TIMEOUT_S = 12


class LiveSummaryTracker:
    """Singleton, stateless across meetings. State lives on
    `MeetingState` — this class is the orchestration layer."""

    _client_factory = staticmethod(_get_client)

    @classmethod
    def maybe_update(
        cls,
        state: MeetingState,
        latest_batch_text: str,
        force: bool = False,
    ) -> Optional[str]:
        """Called once per semantic batch from `_trigger_live_cognition`.

        Args:
            state: the active MeetingState (owns the summary + counters)
            latest_batch_text: the merged text of the semantic batch
                that just completed (what was added since the last call)
            force: if True, run the update regardless of cadence. The
                Phase 12D end-of-meeting orchestrator passes this so a
                short meeting still gets a summary.

        Returns:
            The new summary string if an update fired (and was non-empty),
            else None.
        """
        if not latest_batch_text or not latest_batch_text.strip():
            # Nothing new to summarize — don't burn an LLM call.
            return None

        state.summary_batches_since_update += 1

        if not force and state.summary_batches_since_update < _SUMMARY_BATCH_INTERVAL:
            # Not enough new content yet; wait for more batches.
            return None

        # Reset the counter BEFORE the LLM call. If the call fails we
        # still don't want to spin on every batch — the previous summary
        # is preserved and we'll try again on the next interval.
        state.summary_batches_since_update = 0

        new_summary = cls._call_llm(
            previous_summary=state.summary,
            latest_text=latest_batch_text,
        )

        if not new_summary or not new_summary.strip():
            # Keep the prior summary untouched — better stale than empty.
            logger.debug(
                f"[LIVE SUMMARY] meeting={state.meeting_id} LLM returned empty; "
                f"keeping previous summary"
            )
            return None

        state.summary = new_summary.strip()
        state.summary_updated_at = datetime.now(timezone.utc)
        logger.info(
            f"[LIVE SUMMARY] meeting={state.meeting_id} updated "
            f"({len(state.summary.split())} words)"
        )
        return state.summary

    # ------------------------------------------------------------------
    # LLM call — isolated for easy mocking in tests.
    # ------------------------------------------------------------------
    @classmethod
    def _call_llm(cls, previous_summary: str, latest_text: str) -> str:
        if previous_summary:
            prompt = f"""
You are maintaining a running summary of a live business meeting.

PREVIOUS SUMMARY:
{previous_summary}

NEW DISCUSSION (since last update):
{latest_text}

Update the running summary so it incorporates the new discussion.
Constraints:
- Maximum {_SUMMARY_MAX_SENTENCES} sentences.
- Single paragraph, plain prose. No bullets, no headers, no markdown.
- Speak in the past tense ("The team discussed...", "Engineering reviewed...").
- Keep the SAME high-level topic — only add to it. Do not rewrite from scratch.
- If the new discussion is off-topic or trivial, return the previous summary unchanged.

Output ONLY the updated summary text. No JSON, no preamble.
""".strip()
        else:
            prompt = f"""
You are summarizing the first portion of a live business meeting.

DISCUSSION SO FAR:
{latest_text}

Write a {_SUMMARY_MAX_SENTENCES}-sentence summary of what has been
discussed. Single paragraph, plain prose. No bullets, no headers,
no markdown. Speak in the past tense ("The team discussed...").

Output ONLY the summary text. No JSON, no preamble.
""".strip()

        try:
            client = cls._client_factory()
            response = client.chat.completions.create(
                model=_SUMMARY_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a meeting summarizer. You produce concise, "
                            "factual summaries in plain prose. No formatting."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                timeout=_SUMMARY_TIMEOUT_S,
            )
            text = (response.choices[0].message.content or "").strip()
            # Defensive: strip accidental wrapper quotes / leading "Summary:" labels.
            for prefix in ("Summary:", "summary:", "Updated Summary:"):
                if text.lower().startswith(prefix.lower()):
                    text = text[len(prefix):].strip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1].strip()
            return text
        except Exception as exc:
            logger.error(f"[LIVE SUMMARY] LLM call failed: {exc}")
            return ""
