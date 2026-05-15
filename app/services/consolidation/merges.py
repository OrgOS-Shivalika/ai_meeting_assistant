"""Phase 6D — entity merge suggestion finder.

Within each (organization, scope, entity_type) bucket, find pairs of
entities with high string similarity on their canonical name + aliases.
Pairs above `CONSOLIDATION_MERGE_MIN_SIMILARITY` get queued as
`entity_merge_suggestions` rows with `status='pending'`.

Architectural commitments:

  - **Never auto-merges.** The output is a queue. Phase 7+ adds the UI
    + human approval path.
  - **Sticky rejection.** A partial unique index on the unordered pair
    (`uq_merge_suggestions_pair`) prevents re-proposing a pair after
    rejection. The INSERT uses ON CONFLICT DO NOTHING to absorb
    duplicate proposals across runs.
  - **Bucketing by scope + type.** "Helios" the project must not match
    "Helios" the person; same canonical_name in different scopes is
    legitimately two entities (Phase 3 dedup rule).
  - **No embeddings.** Entities don't carry embeddings; string
    similarity over canonical_name + sorted aliases is fast and
    explainable. PageRank-tier signals are 6.5+ territory.
  - **Skips already-merged or archived entities.** Only 'active' rows
    are eligible candidates — no point suggesting a merge into a
    survivor that's been re-archived.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
from typing import Iterable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import Entity, EntityMergeSuggestion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MergeThresholds:
    min_similarity: float
    max_pairs_per_run: int

    @classmethod
    def from_settings(cls) -> "MergeThresholds":
        return cls(
            min_similarity=settings.CONSOLIDATION_MERGE_MIN_SIMILARITY,
            max_pairs_per_run=settings.CONSOLIDATION_MERGE_MAX_PAIRS_PER_RUN,
        )


def _comparable_text(ent: Entity) -> str:
    """Build the text we compare for similarity: canonical_name plus
    sorted aliases (joined with `|`). Sorting makes the comparison
    order-independent so {A:[a,b]} matches {B:[b,a]}."""
    parts = [(ent.canonical_name or "").strip().lower()]
    if ent.aliases:
        parts.extend(sorted(a.strip().lower() for a in ent.aliases if a))
    return "|".join(parts)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _existing_pair_keys(
    db: Session, organization_id: UUID,
) -> set[frozenset[UUID]]:
    """Pull every pair currently in the suggestions table (any status)
    so we don't re-insert. The partial unique index already enforces
    this at the DB level via ON CONFLICT DO NOTHING, but checking in
    Python keeps the bulk_save_objects path clean."""
    rows = db.execute(
        text(
            "SELECT candidate_a_id, candidate_b_id "
            "FROM entity_merge_suggestions "
            "WHERE organization_id = :o"
        ),
        {"o": str(organization_id)},
    ).all()
    return {frozenset((r.candidate_a_id, r.candidate_b_id)) for r in rows}


def run_merge_suggestions(
    db: Session, *, organization_id: UUID,
    thresholds: MergeThresholds | None = None,
) -> int:
    """Find candidate duplicates, write 'pending' suggestion rows.

    Returns the count of NEW suggestions written (existing pairs in
    any status are skipped). Idempotent — re-running the same data
    produces zero new suggestions.
    """
    thresholds = thresholds or MergeThresholds.from_settings()

    # Pull active entities for this org. Bucket by (scope_type, scope_id,
    # entity_type) — Phase 3's identity key.
    entities = (
        db.query(Entity)
        .filter(
            Entity.organization_id == organization_id,
            Entity.archive_status == "active",
        )
        .all()
    )
    if len(entities) < 2:
        return 0

    buckets: dict[tuple, list[Entity]] = {}
    for e in entities:
        key = (e.scope_type, e.scope_id, e.entity_type)
        buckets.setdefault(key, []).append(e)

    existing = _existing_pair_keys(db, organization_id)
    candidates: list[EntityMergeSuggestion] = []

    for bucket_key, bucket in buckets.items():
        if len(bucket) < 2:
            continue
        # Pre-compute comparable strings to avoid repeated property reads.
        texts = {e.id: _comparable_text(e) for e in bucket}
        for a, b in combinations(bucket, 2):
            pair_key = frozenset((a.id, b.id))
            if pair_key in existing:
                continue
            score = _similarity(texts[a.id], texts[b.id])
            # Skip identical (handled by Phase 3 dedup) and below-threshold.
            if score >= 1.0 or score < thresholds.min_similarity:
                continue
            reason = (
                f"string similarity {score:.2f} on canonical+aliases "
                f"({texts[a.id][:40]!r} ~ {texts[b.id][:40]!r})"
            )
            candidates.append(EntityMergeSuggestion(
                organization_id=organization_id,
                candidate_a_id=a.id,
                candidate_b_id=b.id,
                similarity_score=score,
                reason=reason,
                status="pending",
            ))
            if len(candidates) >= thresholds.max_pairs_per_run:
                break
        if len(candidates) >= thresholds.max_pairs_per_run:
            break

    if not candidates:
        logger.info(
            "merges: org=%s found 0 new candidates (min_similarity=%.2f)",
            organization_id, thresholds.min_similarity,
        )
        return 0

    # bulk_save_objects + ON CONFLICT DO NOTHING isn't directly
    # supported; the partial unique index will raise on a race. Catch
    # the IntegrityError and re-issue one-by-one if that happens.
    try:
        db.bulk_save_objects(candidates)
        db.commit()
        written = len(candidates)
    except Exception as e:
        db.rollback()
        logger.warning(
            "merges: bulk insert hit %s; falling back to per-row insert", e,
        )
        written = 0
        for cand in candidates:
            try:
                db.add(cand); db.commit()
                written += 1
            except Exception as e2:
                db.rollback()
                logger.debug("merges: skipped one suggestion (%s)", e2)
    logger.info(
        "merges: org=%s wrote %d new suggestions (threshold=%.2f)",
        organization_id, written, thresholds.min_similarity,
    )
    return written
