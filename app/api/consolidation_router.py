"""Phase 6D — consolidation HTTP surface.

Read-only at this slice — the suggestion queue is human-reviewable but
6D doesn't ship the "execute merge" action (that lands later when the
UI exists). Endpoints:

  GET    /consolidation/merge-suggestions          — pending list
  PATCH  /consolidation/merge-suggestions/{id}     — decide (merged/rejected)
  POST   /consolidation/chunks/{kind}/{id}/rehydrate
  POST   /consolidation/entities/{id}/rehydrate
  POST   /consolidation/relationships/{id}/rehydrate

The PATCH endpoint only updates the suggestion row's status — it does
NOT execute the merge. A "merged" status records the human decision;
the actual execute-merge job (move mentions, set merged_into pointer)
is deferred to a future phase that ships with a UI.

Every endpoint is org-scoped + 404s on cross-tenant access. DB logic
lives in ``app.services.consolidation.service``.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.dependencies.auth import get_current_user
from app.services.consolidation import service as consolidation_service
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/consolidation", tags=["Consolidation"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EntityRef(BaseModel):
    id: UUID
    name: str
    canonical_name: str
    entity_type: str
    scope_type: str
    scope_id: Optional[int]
    importance_score: Optional[float]
    mention_count_hint: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class MergeSuggestionDetail(BaseModel):
    id: UUID
    candidate_a: EntityRef
    candidate_b: EntityRef
    similarity_score: float
    reason: Optional[str]
    status: Literal["pending", "merged", "rejected"]
    decided_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MergeDecisionRequest(BaseModel):
    status: Literal["merged", "rejected"] = Field(...,
        description="The user's decision. 'merged' records intent; "
                    "the actual entity merge (moving mentions, "
                    "redirecting refs) is deferred to a later phase.")


ChunkKind = Literal["meeting", "document"]


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

@router.get(
    "/merge-suggestions",
    response_model=List[MergeSuggestionDetail],
)
def list_merge_suggestions(
    status: Literal["pending", "merged", "rejected", "all"] = "pending",
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List merge suggestions for the user's org. Default returns only
    `pending` — the inbox for human review."""
    rows = consolidation_service.list_merge_suggestions(
        db, user, status=status, limit=limit,
    )
    return [
        MergeSuggestionDetail(
            id=r.id,
            candidate_a=EntityRef.model_validate(a),
            candidate_b=EntityRef.model_validate(b),
            similarity_score=r.similarity_score,
            reason=r.reason,
            status=r.status,
            decided_at=r.decided_at,
            created_at=r.created_at,
        )
        for r, a, b in rows
    ]


@router.patch(
    "/merge-suggestions/{suggestion_id}",
    response_model=MergeSuggestionDetail,
)
def decide_merge_suggestion(
    suggestion_id: UUID,
    payload: MergeDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Record the human decision on a merge suggestion. Does NOT
    execute the merge — that's a later phase. 'rejected' is sticky:
    a re-run of the consolidation pass skips this pair."""
    row, a, b = consolidation_service.decide_merge_suggestion(
        db, user, suggestion_id=suggestion_id, status=payload.status,
    )
    return MergeSuggestionDetail(
        id=row.id,
        candidate_a=EntityRef.model_validate(a),
        candidate_b=EntityRef.model_validate(b),
        similarity_score=row.similarity_score,
        reason=row.reason,
        status=row.status,
        decided_at=row.decided_at,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Rehydrate
# ---------------------------------------------------------------------------

@router.post("/chunks/{kind}/{chunk_id}/rehydrate", status_code=204)
def rehydrate_chunk(
    kind: ChunkKind,
    chunk_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Flip a chunk's `archive_status` back to 'active'. Returns 204
    on success; 404 when the chunk doesn't exist (or doesn't belong
    to the user's org) or isn't archived."""
    consolidation_service.rehydrate_chunk(db, user, kind=kind, chunk_id=chunk_id)


@router.post("/entities/{entity_id}/rehydrate", status_code=204)
def rehydrate_entity(
    entity_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Flip an entity's `archive_status` back to 'active'. Cannot
    rehydrate `merged_into` entities — those need a separate
    'undo merge' flow (not in 6D)."""
    consolidation_service.rehydrate_entity(db, user, entity_id=entity_id)


@router.post("/relationships/{relationship_id}/rehydrate", status_code=204)
def rehydrate_relationship(
    relationship_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    consolidation_service.rehydrate_relationship(
        db, user, relationship_id=relationship_id,
    )
