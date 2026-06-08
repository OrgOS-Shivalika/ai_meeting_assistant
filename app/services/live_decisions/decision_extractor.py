"""LLM-based live decision extractor — Phase 12B.

Mirrors `app/services/live_tasks/task_extractor.py`. Same one-call-per-batch
shape, same rolling-context overlap, same lazy OpenAI client. Only the
prompt + parsed shape differs.

Why decisions need their own extractor (vs. piggybacking on TaskExtractor):
- TaskExtractor is tuned to be AGGRESSIVE — it captures every commitment,
  even speculative ones, because tasks-without-owners are valuable signal.
  DecisionExtractor is the opposite: be CONSERVATIVE — only emit when
  the text genuinely signals a finalized choice ("we'll go with", "agreed",
  "approved"). False positives are worse than misses for the closing brief
  because incorrectly-flagged decisions show up in spoken output and erode
  trust.
- Output shape differs (decided_by + decision_type instead of owner + deadline).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.ai_agents.openAI_transcript_analyzer import _get_client
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk

logger = logging.getLogger(__name__)


class DecisionExtractor:
    """Extracts finalized decisions from a semantic transcript chunk."""

    # Public knob so tests can swap in a fake client; default lazy-resolves
    # the real OpenAI client from the existing analyzer module.
    _client_factory = staticmethod(_get_client)

    @classmethod
    def extract_from_chunk(
        cls,
        chunk: LiveTranscriptChunk,
        rolling_context: str,
    ) -> List[Dict[str, Any]]:
        """One LLM call per semantic batch. Returns raw dicts (not yet
        stabilized) shaped like:

            {
                "decision": "Migrate auth service before payment service",
                "decided_by": "Engineering team",
                "decision_type": "technical",
                "confidence": 0.92,
                "source_speaker": "...",
                "source_timestamp": "...",
                "transcript_chunk_id": 42,
            }
        """
        prompt = f"""
You are a conservative real-time decision detection engine for meetings.
Analyze the ROLLING CONTEXT to understand the discussion, then extract
FINALIZED decisions ONLY from the CURRENT CHUNK.

ROLLING CONTEXT (Past discussion for reference ONLY):
{rolling_context}

CURRENT CHUNK (Extract decisions from here ONLY):
Speaker: {chunk.speaker_name}
Text: {chunk.text}

Rules:
1. Extract ONLY genuine, finalized decisions. A decision is a choice
   the group has converged on. Phrases that signal a decision:
   "we'll go with", "let's do", "agreed", "approved", "the decision
   is", "we've decided", "going with option A", "moving forward with".
2. DO NOT extract:
   - Suggestions ("we could", "maybe we should")
   - Open questions ("should we?")
   - Speculation ("if we did X then Y")
   - Action items / tasks (those are handled separately)
   - Pure information sharing ("the data shows X")
3. DO NOT extract decisions that appear ONLY in ROLLING CONTEXT.
   They have already been processed.
4. Identify `decided_by`: the speaker, or a group name if explicit
   ("the team agreed"). Use null if unclear.
5. Classify `decision_type` as one of:
   - "process"     — workflow / how-we-work decisions
   - "technical"   — tech choices, architecture, tools
   - "scheduling"  — timing, dates, ordering
   - "ownership"   — who owns what (not WHAT to do, that's a task)
   - "scope"       — what's in / out of scope
   - "other"
6. Confidence scale (0.0 - 1.0):
   - 0.9+ : Explicit confirmation phrase used ("agreed", "approved")
   - 0.7-0.9 : Strong directional language ("let's go with", "we'll do")
   - 0.5-0.7 : Implied decision but slightly fuzzy
   - Below 0.5 : DO NOT EMIT — too uncertain for a decision

Response Format (JSON only, no prose):
{{
  "decisions": [
    {{
      "decision": "Migrate auth service before payment service",
      "decided_by": "Engineering team",
      "decision_type": "technical",
      "confidence": 0.92
    }}
  ]
}}

If nothing qualifies, return {{"decisions": []}}.
"""
        try:
            client = cls._client_factory()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a real-time decision extractor. Be CONSERVATIVE. "
                            "You must always respond with valid JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                timeout=10,
            )

            result = json.loads(response.choices[0].message.content or "{}")
            extracted_raw: List[Dict[str, Any]] = []

            for d in result.get("decisions", []):
                # Drop anything below the conservative-floor confidence.
                # Mirrors the prompt rule and gives the stabilizer a clean
                # signal — it shouldn't have to second-guess.
                conf = float(d.get("confidence", 0.0))
                if conf < 0.5:
                    continue
                decision_text = d.get("decision")
                if not decision_text:
                    continue
                extracted_raw.append({
                    "decision": decision_text,
                    "decided_by": d.get("decided_by"),
                    "decision_type": d.get("decision_type", "other"),
                    "confidence": conf,
                    "source_speaker": chunk.speaker_name,
                    "source_timestamp": chunk.timestamp,
                    "transcript_chunk_id": chunk.sequence_number,
                })

            return extracted_raw

        except Exception as e:
            logger.error(f"Live decision extraction failed: {e}")
            return []
