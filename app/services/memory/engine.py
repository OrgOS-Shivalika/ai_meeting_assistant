"""Phase 1C — MeetingMemoryEngine: post-meeting fact distiller.

Runs ONCE per completed meeting from the meeting pipeline. Reads:
  - meeting.summary + meeting.transcript_text
  - meeting.tasks (relationship — already exists)
  - top-20 prior facts for the same (org, category, team) scope
Then calls gpt-4o-mini ONCE with a strict-JSON anti-hallucination
prompt, validates the output, embeds the surviving facts in a single
batch call, dedupes against existing facts (cosine), and inserts /
supersedes / bumps as appropriate.

Wrapped at the call site by meeting_pipeline.py — a distiller failure
never fails the meeting.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai_agents.openAI_transcript_analyzer import _get_client
from app.ai_agents.prompts.memory_engine_prompt import (
    FACT_TYPES, MEMORY_ENGINE_PROMPT_VERSION, build_prompt,
)
from app.db.models import Meeting
from app.utils.enums import MeetingStatus
from app.services.embedder import Embedder
from app.services.memory.access import MemoryAccess

logger = logging.getLogger(__name__)

# Cosine distance, NOT similarity — pgvector's <=> operator returns
# distance = 1 - cos_sim. We compare in distance space because that's
# what the index speaks.
DUP_DISTANCE_THRESHOLD = 0.15        # ~ similarity 0.85 — exact dup
SUPERSEDE_DISTANCE_THRESHOLD = 0.30  # ~ similarity 0.70 — same topic, maybe contradicting

MAX_FACTS_PER_MEETING = 10
LLM_TIMEOUT_S = 30
LLM_MAX_TOKENS = 1200      # generous for ~10 facts × ~100 tok each

# fact_types where "the latest one wins" is semantically defensible.
# preferences/patterns/risks/open_questions co-exist with prior versions.
SUPERSEDE_ELIGIBLE_TYPES = frozenset({"ownership", "decision", "event"})


class ExtractedFact(BaseModel):
    """One fact as emitted by the distiller LLM. Mirrors the prompt schema."""
    fact: str = Field(min_length=4, max_length=400)
    fact_type: str
    subject: Optional[str] = Field(default=None, max_length=128)
    source_excerpt: str = Field(min_length=4, max_length=600)
    importance_score: float = Field(ge=0.0, le=1.0, default=0.5)
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.7)
    supersedes_id: Optional[UUID] = None

    @field_validator("fact_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in FACT_TYPES:
            raise ValueError(f"fact_type must be one of {FACT_TYPES}")
        return v


class _DistillerOutput(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list, max_length=MAX_FACTS_PER_MEETING)


class MeetingMemoryEngine:
    """Post-meeting distiller. One-shot per meeting; idempotent on re-run."""

    PROMPT_VERSION = MEMORY_ENGINE_PROMPT_VERSION

    @classmethod
    def distill_for_meeting(
        cls,
        db: Session,
        meeting_id: int,
        *,
        force: bool = False,
    ) -> dict:
        """Distill durable facts from one completed meeting.

        Returns a small report dict for logging. NEVER raises — the
        caller (meeting_pipeline) wraps in try/except too, but we
        return cleanly so the pipeline-level except is a true safety
        net rather than the normal path.
        """
        t0 = time.perf_counter()
        meeting: Meeting | None = db.get(Meeting, meeting_id)
        if not meeting:
            return {"ok": False, "reason": "meeting_not_found"}
        if meeting.status != MeetingStatus.COMPLETED:
            return {"ok": False, "reason": f"status={meeting.status}"}

        # ---- Idempotency guard ---------------------------------------
        # If force=False and any active facts already exist for this
        # meeting, skip — likely a retry after a successful run.
        if not force:
            already = db.execute(
                text(
                    "SELECT 1 FROM org_memory_facts "
                    "WHERE source_meeting_id = :mid "
                    "AND archive_status = 'active' LIMIT 1"
                ),
                {"mid": meeting_id},
            ).first()
            if already:
                return {"ok": True, "skipped": "already_distilled"}

        # ---- 1. Build prompt context ---------------------------------
        # meeting.tasks is the relationship to the Task table; decisions
        # have no table yet (Phase 4 — Sachiv typed memory), so we pass
        # an empty list and let the LLM read the summary for context.
        task_dicts = [
            {"task": t.task, "owner": t.owner_name}
            for t in (meeting.tasks or [])
            if t.task
        ][:20]
        prior = MemoryAccess.get_recent(
            db,
            organization_id=meeting.organization_id,
            category_id=meeting.category_id,
            team_id=meeting.team_id,
            limit=20,
        )
        prior_serialized = [
            {"id": str(p.id), "fact": p.fact, "fact_type": p.fact_type, "subject": p.subject}
            for p in prior
        ]
        prompt = build_prompt(
            meeting_summary=(meeting.summary or "")[:2000],
            decisions=[],   # Phase 4 — Sachiv typed decisions table
            tasks=task_dicts,
            prior_facts=prior_serialized,
        )

        # ---- 2. Call gpt-4o-mini ------------------------------------
        try:
            client = _get_client()
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a strict JSON fact distiller."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,   # low — extraction, not creativity
                max_tokens=LLM_MAX_TOKENS,
                timeout=LLM_TIMEOUT_S,
            )
            raw = resp.choices[0].message.content or "{}"
            usage = getattr(resp, "usage", None)
        except Exception as e:
            logger.warning("MemoryEngine LLM call failed for meeting=%s: %s", meeting_id, e)
            return {"ok": False, "reason": "llm_failed", "error": str(e)[:200]}

        # ---- 3. Validate JSON ---------------------------------------
        try:
            parsed_raw = json.loads(raw)
            parsed = _DistillerOutput.model_validate(parsed_raw)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("MemoryEngine parse failed for meeting=%s: %s", meeting_id, e)
            return {"ok": False, "reason": "bad_json", "error": str(e)[:200]}

        facts = parsed.facts[:MAX_FACTS_PER_MEETING]
        if not facts:
            return {
                "ok": True, "prompt_version": cls.PROMPT_VERSION,
                "facts_extracted": 0, "facts_inserted": 0,
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            }

        # ---- 4. Excerpt verification (anti-hallucination layer 2) ----
        # The LLM was told to cite a verbatim quote. We check that quote
        # actually appears in the transcript (or summary, as fallback).
        # If it doesn't, the model invented the fact — drop it.
        transcript_hay = _normalize(
            (meeting.transcript_text or "") + " " + (meeting.summary or "")
        )
        verified: list[ExtractedFact] = []
        dropped_no_excerpt = 0
        for f in facts:
            if _normalize(f.source_excerpt) in transcript_hay:
                verified.append(f)
            else:
                dropped_no_excerpt += 1
        if not verified:
            return {
                "ok": True, "prompt_version": cls.PROMPT_VERSION,
                "facts_extracted": len(facts),
                "facts_inserted": 0, "dropped_no_excerpt": dropped_no_excerpt,
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            }

        # ---- 5. Embed surviving facts in ONE batch call -------------
        try:
            vectors = Embedder().embed([f.fact for f in verified])
        except Exception as e:
            logger.warning("MemoryEngine embed failed for meeting=%s: %s", meeting_id, e)
            return {"ok": False, "reason": "embedding_failed", "error": str(e)[:200]}

        # ---- 6. Dedup + supersede + insert --------------------------
        inserted = bumped = superseded = 0
        try:
            for fact, vec in zip(verified, vectors):
                nn = _nearest_neighbor(
                    db,
                    org_id=meeting.organization_id,
                    category_id=meeting.category_id,
                    team_id=meeting.team_id,
                    vec=vec,
                )
                if nn is not None and nn["distance"] <= DUP_DISTANCE_THRESHOLD \
                        and nn["fact_type"] == fact.fact_type:
                    # Pure duplicate of same-type fact → bump signals, don't insert.
                    MemoryAccess.bump_access(db, [nn["id"]])
                    bumped += 1
                    continue

                # Supersede: either the LLM marked it explicitly OR we see
                # a close-but-not-identical same-type neighbor and the
                # fact_type allows it.
                supersedes_id = fact.supersedes_id
                if supersedes_id is None and nn is not None \
                        and nn["fact_type"] == fact.fact_type \
                        and DUP_DISTANCE_THRESHOLD < nn["distance"] <= SUPERSEDE_DISTANCE_THRESHOLD \
                        and fact.fact_type in SUPERSEDE_ELIGIBLE_TYPES:
                    supersedes_id = nn["id"]

                # Insert. IntegrityError on race-condition re-runs is
                # caught and counted, not propagated.
                try:
                    new_row = MemoryAccess.insert(
                        db,
                        organization_id=meeting.organization_id,
                        category_id=meeting.category_id,
                        team_id=meeting.team_id,
                        fact=fact.fact,
                        fact_type=fact.fact_type,
                        subject=fact.subject,
                        source_meeting_id=meeting.id,
                        source_excerpt=fact.source_excerpt,
                        importance_score=fact.importance_score,
                        confidence_score=fact.confidence_score,
                        embedding=vec,
                        embedding_model="text-embedding-3-small",
                        metadata_json={
                            "prompt_version": cls.PROMPT_VERSION,
                            "llm_model": "gpt-4o-mini",
                        },
                    )
                    inserted += 1
                    if supersedes_id is not None:
                        MemoryAccess.mark_superseded(db, old_id=supersedes_id, new_id=new_row.id)
                        superseded += 1
                except IntegrityError as ie:
                    db.rollback()
                    logger.info(
                        "MemoryEngine: dedup collision (meeting=%s fact=%r): %s",
                        meeting_id, fact.fact[:60], ie.orig.__class__.__name__,
                    )

            db.commit()
        except Exception as e:
            db.rollback()
            logger.exception("MemoryEngine insert phase failed for meeting=%s", meeting_id)
            return {"ok": False, "reason": "db_failed", "error": str(e)[:200]}

        return {
            "ok": True,
            "prompt_version": cls.PROMPT_VERSION,
            "facts_extracted": len(facts),
            "facts_verified": len(verified),
            "facts_inserted": inserted,
            "facts_bumped": bumped,
            "facts_superseded": superseded,
            "dropped_no_excerpt": dropped_no_excerpt,
            "duration_ms": int((time.perf_counter() - t0) * 1000),
            "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
            "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        }


# -------------------------- helpers --------------------------------------

def _normalize(s: str) -> str:
    """Lowercase + collapse whitespace. Used for excerpt-in-transcript check."""
    return " ".join((s or "").lower().split())


def _nearest_neighbor(db: Session, *, org_id, category_id, team_id, vec) -> dict | None:
    """Top-1 cosine nearest neighbor within the same org/scope.

    Same-scope only: we never dedup across teams/categories. "Sarah
    owns OAuth" in TeamA is a different fact from the same sentence
    in TeamB.
    """
    row = db.execute(
        text("""
            SELECT id, fact_type, (embedding <=> CAST(:vec AS vector)) AS distance
            FROM org_memory_facts
            WHERE organization_id = :org
              AND archive_status = 'active'
              AND (CAST(:cat AS integer) IS NULL OR category_id = :cat)
              AND (CAST(:team AS integer) IS NULL OR team_id = :team)
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT 1
        """),
        {"vec": str(vec), "org": str(org_id), "cat": category_id, "team": team_id},
    ).first()
    if not row:
        return None
    return {"id": row.id, "fact_type": row.fact_type, "distance": float(row.distance)}
