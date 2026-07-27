"""Phase 3D — graph read API.

Endpoints (all org-scoped via `get_current_user`):

    GET  /entities                — paginated list with scope/type/q filters
    GET  /entities/{entity_id}    — detail: row + both-direction rels + recent mentions
    GET  /meetings/{meeting_id}/graph — debug/inspection: everything a meeting emitted

Tenant isolation contract (carried over from `/search` in Phase 2D):

- `scope_id` belonging to a sibling org returns 404, not "0 results".
- An `entity_id` from a sibling org returns 404.
- A `meeting_id` from a sibling org returns 404.

Access tracking (Phase 6 will read these):

- `/entities` and `/entities/{id}` bump `last_accessed_at` and
  `access_count` on the entities they return.
- `/meetings/{id}/graph` does NOT bump — it's a debug/admin view and we
  don't want it skewing the ranking signal.

DB logic lives in ``app.services.graph_query_service``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.schemas.graph_schema import (
    EntityDetail,
    EntityListResponse,
    MeetingGraphResponse,
)
from app.services import graph_query_service

router = APIRouter(tags=["Graph"])


# ---------------------------------------------------------------------------
# GET /entities — paginated list
# ---------------------------------------------------------------------------

@router.get("/entities", response_model=EntityListResponse)
def list_entities(
    scope: Optional[str] = Query(default=None, pattern="^(team|category|global)$"),
    scope_id: Optional[int] = Query(default=None),
    entity_type: Optional[str] = Query(
        default=None, pattern="^(person|project|topic|decision|commitment)$",
    ),
    q: Optional[str] = Query(default=None, min_length=1, max_length=200,
                             description="Substring match against name or canonical_name (case-insensitive)."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return graph_query_service.list_entities(
        db, user,
        scope=scope, scope_id=scope_id, entity_type=entity_type,
        q=q, limit=limit, offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /entities/{id} — detail with both-direction relationships + recent mentions
# ---------------------------------------------------------------------------

@router.get("/entities/{entity_id}", response_model=EntityDetail)
def get_entity(
    entity_id: str,
    mentions_limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return graph_query_service.get_entity(
        db, user, entity_id=entity_id, mentions_limit=mentions_limit,
    )


# ---------------------------------------------------------------------------
# GET /meetings/{id}/graph — everything emitted by a meeting
# ---------------------------------------------------------------------------

@router.get("/meetings/{meeting_id}/graph", response_model=MeetingGraphResponse)
def get_meeting_graph(
    meeting_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return graph_query_service.get_meeting_graph(db, user, meeting_id=meeting_id)
