"""Phase 6D — consolidation HTTP-surface DB logic.

Extracted from ``app/api/consolidation_router.py`` so the router stays a
thin transport layer. Functions take the SQLAlchemy ``Session`` plus the
current user and raise ``HTTPException`` for tenant-isolation / not-found /
conflict failures — mirroring the ``category_service`` convention.

The read/decide functions return the suggestion row already hydrated with
its two candidate ``Entity`` rows as ``(suggestion, entity_a, entity_b)``
tuples; the router owns the Pydantic response-model assembly (its schemas
live in the router module).

The PATCH path only updates the suggestion row's status — it does NOT
execute the merge. A "merged" status records the human decision; the
actual execute-merge job is deferred to a future phase.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.models import (
    DocumentChunk,
    Entity,
    EntityMergeSuggestion,
    MeetingChunk,
    Relationship,
)
from app.services.consolidation.archive import rehydrate as _rehydrate
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

def list_merge_suggestions(
    db: Session,
    user,
    *,
    status: Literal["pending", "merged", "rejected", "all"],
    limit: int,
) -> list[tuple[EntityMergeSuggestion, Entity, Entity]]:
    """List merge suggestions for the user's org, hydrated with their
    candidate entities. Default caller passes `pending` — the inbox for
    human review. Rows whose candidates have vanished (cascade race) are
    skipped — treated as already-resolved."""
    q = (
        db.query(EntityMergeSuggestion)
        .filter(EntityMergeSuggestion.organization_id == user.organization_id)
    )
    if status != "all":
        q = q.filter(EntityMergeSuggestion.status == status)
    rows = (
        q.order_by(desc(EntityMergeSuggestion.similarity_score),
                   desc(EntityMergeSuggestion.created_at))
         .limit(min(max(limit, 1), 500))
         .all()
    )
    # Hydrate entity refs with one extra query.
    if not rows:
        return []
    entity_ids: set[UUID] = set()
    for r in rows:
        entity_ids.add(r.candidate_a_id)
        entity_ids.add(r.candidate_b_id)
    entities = {
        e.id: e for e in db.query(Entity).filter(
            Entity.organization_id == user.organization_id,
            Entity.id.in_(entity_ids),
        ).all()
    }
    out: list[tuple[EntityMergeSuggestion, Entity, Entity]] = []
    for r in rows:
        a = entities.get(r.candidate_a_id)
        b = entities.get(r.candidate_b_id)
        # Skip rows whose candidates have vanished (cascade race) —
        # treat as already-resolved.
        if a is None or b is None:
            continue
        out.append((r, a, b))
    return out


def decide_merge_suggestion(
    db: Session,
    user,
    *,
    suggestion_id: UUID,
    status: Literal["merged", "rejected"],
) -> tuple[EntityMergeSuggestion, Entity, Entity]:
    """Record the human decision on a merge suggestion. Does NOT
    execute the merge — that's a later phase. 'rejected' is sticky:
    a re-run of the consolidation pass skips this pair."""
    row = db.query(EntityMergeSuggestion).filter(
        EntityMergeSuggestion.id == suggestion_id,
        EntityMergeSuggestion.organization_id == user.organization_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if row.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Suggestion already decided ({row.status})",
        )
    row.status = status
    row.decided_by_user_id = user.id
    row.decided_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(row)
    # Same hydration as the list endpoint.
    a = db.query(Entity).filter(Entity.id == row.candidate_a_id).first()
    b = db.query(Entity).filter(Entity.id == row.candidate_b_id).first()
    if a is None or b is None:
        raise HTTPException(status_code=404, detail="Candidate entities not found")
    return row, a, b


# ---------------------------------------------------------------------------
# Rehydrate
# ---------------------------------------------------------------------------

def rehydrate_chunk(
    db: Session,
    user,
    *,
    kind: Literal["meeting", "document"],
    chunk_id: UUID,
) -> None:
    """Flip a chunk's `archive_status` back to 'active'. 404 when the
    chunk doesn't exist (or doesn't belong to the user's org) or isn't
    archived."""
    model = MeetingChunk if kind == "meeting" else DocumentChunk
    ok = _rehydrate(db, organization_id=user.organization_id,
                    model=model, row_id=chunk_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chunk not archived or not found")


def rehydrate_entity(
    db: Session,
    user,
    *,
    entity_id: UUID,
) -> None:
    """Flip an entity's `archive_status` back to 'active'. Cannot
    rehydrate `merged_into` entities — those need a separate
    'undo merge' flow (not in 6D)."""
    # Manually filter so we can distinguish "merged" from "not found".
    row = db.query(Entity).filter(
        Entity.id == entity_id,
        Entity.organization_id == user.organization_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    if row.archive_status == "merged_into":
        raise HTTPException(
            status_code=409,
            detail="Cannot rehydrate a merged entity; undo the merge first.",
        )
    if row.archive_status != "archived":
        raise HTTPException(status_code=404, detail="Entity not archived")
    row.archive_status = "active"
    db.commit()


def rehydrate_relationship(
    db: Session,
    user,
    *,
    relationship_id: UUID,
) -> None:
    ok = _rehydrate(
        db, organization_id=user.organization_id,
        model=Relationship, row_id=relationship_id,
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Relationship not archived or not found",
        )
