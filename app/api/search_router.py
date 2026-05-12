"""Phase 2D search API.

POST /search                       — semantic search across the user's org.
GET  /meetings/{meeting_id}/chunks — inspection / debug view of a meeting's
                                     embedded chunks.

Both endpoints are org-scoped from `get_current_user`. The `scope_id` body
parameter narrows further (to a category or team within the org); we
validate the scope belongs to the user's org before running the query so
a forged id from a sibling tenant returns 404, not silently empty hits.

Retrieval uses pgvector's cosine-distance operator (`<=>`) via the HNSW
index built in 2A. We expose `similarity = clamp(1 - distance, 0, 1)`
so the API contract is intuitive (1.0 = identical) and stable regardless
of the embedding model's preferred distance metric.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.config.settings import settings
from app.db.models import Category, Meeting, MeetingChunk, Team
from app.dependencies.auth import get_current_user
from app.schemas.search_schema import (
    CategoryRef,
    MeetingChunksResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    TeamRef,
)
from app.services.embedder import Embedder
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(tags=["Search"])

# One embedder instance per process — it's stateless beyond the lazy
# OpenAI client.
_embedder: Embedder | None = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _validate_scope(db: Session, user, scope: str, scope_id: int | None) -> None:
    """Enforce that `scope_id` (when present) refers to a category/team
    that lives inside the requesting user's organization. Returns 404
    otherwise — never reveals existence of objects in sibling orgs."""
    if scope == "category":
        cat = db.execute(
            select(Category.id).where(
                Category.id == scope_id,
                Category.organization_id == user.organization_id,
            )
        ).first()
        if cat is None:
            raise HTTPException(status_code=404, detail="Category not found")
    elif scope == "team":
        team = db.execute(
            select(Team.id)
            .join(Category, Team.category_id == Category.id)
            .where(
                Team.id == scope_id,
                Category.organization_id == user.organization_id,
            )
        ).first()
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")


def _build_hit(row, similarity: float) -> SearchHit:
    """Translate one SELECT row into a SearchHit. Keep this in one place
    so both endpoints stay consistent."""
    chunk: MeetingChunk = row.MeetingChunk
    return SearchHit(
        chunk_id=chunk.id,
        meeting_id=chunk.meeting_id,
        meeting_title=row.meeting_title,
        meeting_url=row.meeting_url,
        scheduled_at=row.scheduled_at,
        chunk_index=chunk.chunk_index,
        chunk_text=chunk.text,
        token_count=chunk.token_count,
        speakers=list(chunk.speakers or []),
        start_timestamp=chunk.start_timestamp,
        end_timestamp=chunk.end_timestamp,
        similarity=similarity,
        category=(
            CategoryRef(id=row.category_id, name=row.category_name, color=row.category_color)
            if row.category_id is not None and row.category_name is not None
            else None
        ),
        team=(
            TeamRef(id=row.team_id, name=row.team_name)
            if row.team_id is not None and row.team_name is not None
            else None
        ),
    )


@router.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _validate_scope(db, user, payload.scope, payload.scope_id)

    embedder = _get_embedder()
    try:
        query_vec = embedder.embed([payload.query])[0]
    except RuntimeError as exc:
        # OPEN_API_KEY missing or provider configuration issue. Bubble up
        # as a 503 so the client knows the server can't perform the
        # operation right now (rather than the user's input being bad).
        logger.error("Embedder unavailable for search: %s", exc)
        raise HTTPException(status_code=503, detail="Search backend unavailable")

    distance = MeetingChunk.embedding.cosine_distance(query_vec).label("distance")
    max_distance = 1.0 - payload.min_similarity

    stmt = (
        select(
            MeetingChunk,
            distance,
            Meeting.title.label("meeting_title"),
            Meeting.meeting_url.label("meeting_url"),
            Meeting.scheduled_at.label("scheduled_at"),
            Category.id.label("category_id"),
            Category.name.label("category_name"),
            Category.color.label("category_color"),
            Team.id.label("team_id"),
            Team.name.label("team_name"),
        )
        .join(Meeting, MeetingChunk.meeting_id == Meeting.id)
        .outerjoin(Category, MeetingChunk.category_id == Category.id)
        .outerjoin(Team, MeetingChunk.team_id == Team.id)
        .where(MeetingChunk.organization_id == user.organization_id)
        .order_by(distance)
        .limit(payload.top_k)
    )

    # Scope narrowing. min_similarity is applied in SQL via a derived
    # `distance` expression so the HNSW index keeps doing the heavy lifting.
    if payload.scope == "category":
        stmt = stmt.where(MeetingChunk.category_id == payload.scope_id)
    elif payload.scope == "team":
        stmt = stmt.where(MeetingChunk.team_id == payload.scope_id)
    if payload.min_similarity > 0.0:
        stmt = stmt.where(
            MeetingChunk.embedding.cosine_distance(query_vec) <= max_distance
        )

    rows = db.execute(stmt).all()
    hits: list[SearchHit] = []
    chunk_ids: list = []
    for row in rows:
        sim = _clamp01(1.0 - float(row.distance))
        hits.append(_build_hit(row, sim))
        chunk_ids.append(row.MeetingChunk.id)

    # Phase 6 will use these for recency/importance reranking; even
    # though we don't read them yet, populating them from day one keeps
    # the "Knowledge OS" contract real.
    if chunk_ids:
        now = datetime.now(timezone.utc)
        db.query(MeetingChunk).filter(MeetingChunk.id.in_(chunk_ids)).update(
            {
                MeetingChunk.last_accessed_at: now,
                MeetingChunk.access_count: MeetingChunk.access_count + 1,
            },
            synchronize_session=False,
        )
        db.commit()

    logger.info(
        "search(org=%s, scope=%s, scope_id=%s, top_k=%d): %d hits",
        user.organization_id,
        payload.scope,
        payload.scope_id,
        payload.top_k,
        len(hits),
    )
    return SearchResponse(
        query=payload.query,
        scope=payload.scope,
        scope_id=payload.scope_id,
        embedding_model=embedder.model,
        hits=hits,
    )


@router.get("/meetings/{meeting_id}/chunks", response_model=MeetingChunksResponse)
def get_meeting_chunks(
    meeting_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Returns every chunk produced for a meeting, in `chunk_index`
    order. Org-scoped: a meeting belonging to a sibling org is treated
    as nonexistent (404)."""
    meeting = db.execute(
        select(Meeting).where(
            Meeting.id == meeting_id,
            Meeting.organization_id == user.organization_id,
        )
    ).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    stmt = (
        select(
            MeetingChunk,
            Meeting.title.label("meeting_title"),
            Meeting.meeting_url.label("meeting_url"),
            Meeting.scheduled_at.label("scheduled_at"),
            Category.id.label("category_id"),
            Category.name.label("category_name"),
            Category.color.label("category_color"),
            Team.id.label("team_id"),
            Team.name.label("team_name"),
        )
        .join(Meeting, MeetingChunk.meeting_id == Meeting.id)
        .outerjoin(Category, MeetingChunk.category_id == Category.id)
        .outerjoin(Team, MeetingChunk.team_id == Team.id)
        .where(
            MeetingChunk.meeting_id == meeting_id,
            MeetingChunk.organization_id == user.organization_id,
        )
        .order_by(MeetingChunk.chunk_index)
    )

    # similarity=1.0 is a placeholder so the response shape mirrors /search.
    # The inspection endpoint isn't ranking anything; consumers know to
    # ignore it (or we can drop it from `MeetingChunksResponse` later).
    chunks = [_build_hit(row, similarity=1.0) for row in db.execute(stmt).all()]
    return MeetingChunksResponse(
        meeting_id=meeting.id,
        embedding_status=meeting.embedding_status,
        embedded_at=meeting.embedded_at,
        chunks=chunks,
    )
