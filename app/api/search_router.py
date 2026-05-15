"""Phase 2D / 4E search API.

POST /search                       — semantic search across the user's org.
GET  /meetings/{meeting_id}/chunks — inspection of a meeting's embedded chunks.
GET  /documents/{kind}/{doc_id}/chunks
                                   — inspection of a document's chunks.

Both list endpoints are org-scoped from `get_current_user`. The `scope`
body parameter narrows further (to a category or team within the org); we
validate the scope belongs to the user's org before running the query so
a forged id from a sibling tenant returns 404, not silently empty hits.

Phase 4E: the search endpoint is polymorphic over `meeting_chunks` and
`document_chunks`. Both tables carry a 1536-d `embedding` column with
the same HNSW + cosine_ops index, so we issue two parallel pgvector
queries (each top-K under the HNSW path) and merge by distance in
Python. This avoids fighting SQLAlchemy UNION semantics with mismatched
column types, while still letting each table's HNSW index do the heavy
lifting. The `sources` body param can narrow the union to one side.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.config.settings import settings
from app.db.models import (
    Category, CategoryDocument, DocumentChunk, Meeting, MeetingChunk, Team,
    TeamDocument,
)
from app.dependencies.auth import get_current_user
from app.schemas.search_schema import (
    CategoryRef,
    DocumentChunksResponse,
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


# ---------------------------------------------------------------------------
# Hit builders — one per source type. Keep these in lock-step with the
# columns selected in the corresponding query.
# ---------------------------------------------------------------------------

def _build_meeting_hit(row, similarity: float) -> SearchHit:
    chunk: MeetingChunk = row.MeetingChunk
    return SearchHit(
        source_type="meeting",
        chunk_id=chunk.id,
        chunk_index=chunk.chunk_index,
        chunk_text=chunk.text,
        token_count=chunk.token_count,
        similarity=similarity,
        meeting_id=chunk.meeting_id,
        meeting_title=row.meeting_title,
        meeting_url=row.meeting_url,
        scheduled_at=row.scheduled_at,
        speakers=list(chunk.speakers or []),
        start_timestamp=chunk.start_timestamp,
        end_timestamp=chunk.end_timestamp,
        category=(
            CategoryRef(id=row.category_id, name=row.category_name,
                        color=row.category_color)
            if row.category_id is not None and row.category_name is not None
            else None
        ),
        team=(
            TeamRef(id=row.team_id, name=row.team_name)
            if row.team_id is not None and row.team_name is not None
            else None
        ),
    )


def _build_document_hit(row, similarity: float) -> SearchHit:
    chunk: DocumentChunk = row.DocumentChunk
    meta = chunk.metadata_json or {}
    subtype = meta.get("source_subtype")
    if isinstance(subtype, list):
        # The chunker stashes a list when a chunk straddles formats; we
        # show the first one. (For our parsers it never happens — a chunk
        # is always one subtype — but the schema accepts it.)
        subtype = subtype[0] if subtype else None
    return SearchHit(
        source_type="document",
        chunk_id=chunk.id,
        chunk_index=chunk.chunk_index,
        chunk_text=chunk.text,
        token_count=chunk.token_count,
        similarity=similarity,
        document_id=row.document_id,
        document_name=row.document_name,
        document_kind=chunk.document_type,
        page_number=chunk.page_number,
        section_path=chunk.section_path,
        source_subtype=subtype,
        category=(
            CategoryRef(id=row.category_id, name=row.category_name,
                        color=row.category_color)
            if row.category_id is not None and row.category_name is not None
            else None
        ),
        team=(
            TeamRef(id=row.team_id, name=row.team_name)
            if row.team_id is not None and row.team_name is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Per-source query builders. Each returns (hits, chunk_ids) so the caller
# can update `last_accessed_at` after the merge.
# ---------------------------------------------------------------------------

def _search_meeting_chunks(
    db: Session, user, payload: SearchRequest, query_vec
) -> tuple[list[SearchHit], list]:
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
        .where(
            MeetingChunk.organization_id == user.organization_id,
            # Phase 6D — archived chunks are excluded from user-facing
            # search. The inspection endpoints below (which power "show
            # me everything in this meeting") deliberately do NOT
            # filter so admins can see the full archive.
            MeetingChunk.archive_status == "active",
        )
        .order_by(distance)
        .limit(payload.top_k)
    )
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
    chunk_ids = []
    for row in rows:
        sim = _clamp01(1.0 - float(row.distance))
        hits.append(_build_meeting_hit(row, sim))
        chunk_ids.append(row.MeetingChunk.id)
    return hits, chunk_ids


def _search_document_chunks(
    db: Session, user, payload: SearchRequest, query_vec
) -> tuple[list[SearchHit], list]:
    """Same structure as `_search_meeting_chunks` but reaches into
    `document_chunks` and outer-joins both possible parents. Only one
    parent is set per row (CHECK enforced) so the COALESCE on the
    label-side picks whichever fired."""
    from sqlalchemy import func

    distance = DocumentChunk.embedding.cosine_distance(query_vec).label("distance")
    max_distance = 1.0 - payload.min_similarity

    stmt = (
        select(
            DocumentChunk,
            distance,
            # Coalesce the doc id / name across the two parent tables so
            # the hit builder doesn't have to inspect document_type.
            func.coalesce(CategoryDocument.id, TeamDocument.id).label("document_id"),
            func.coalesce(CategoryDocument.name, TeamDocument.name).label("document_name"),
            Category.id.label("category_id"),
            Category.name.label("category_name"),
            Category.color.label("category_color"),
            Team.id.label("team_id"),
            Team.name.label("team_name"),
        )
        .outerjoin(CategoryDocument, DocumentChunk.category_document_id == CategoryDocument.id)
        .outerjoin(TeamDocument, DocumentChunk.team_document_id == TeamDocument.id)
        .outerjoin(Category, DocumentChunk.category_id == Category.id)
        .outerjoin(Team, DocumentChunk.team_id == Team.id)
        .where(
            DocumentChunk.organization_id == user.organization_id,
            DocumentChunk.archive_status == "active",
        )
        .order_by(distance)
        .limit(payload.top_k)
    )
    if payload.scope == "category":
        stmt = stmt.where(DocumentChunk.category_id == payload.scope_id)
    elif payload.scope == "team":
        stmt = stmt.where(DocumentChunk.team_id == payload.scope_id)
    if payload.min_similarity > 0.0:
        stmt = stmt.where(
            DocumentChunk.embedding.cosine_distance(query_vec) <= max_distance
        )

    rows = db.execute(stmt).all()
    hits: list[SearchHit] = []
    chunk_ids = []
    for row in rows:
        sim = _clamp01(1.0 - float(row.distance))
        hits.append(_build_document_hit(row, sim))
        chunk_ids.append(row.DocumentChunk.id)
    return hits, chunk_ids


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

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
        logger.error("Embedder unavailable for search: %s", exc)
        raise HTTPException(status_code=503, detail="Search backend unavailable")

    meeting_hits: list[SearchHit] = []
    document_hits: list[SearchHit] = []
    meeting_chunk_ids: list = []
    document_chunk_ids: list = []

    if payload.sources in ("all", "meetings"):
        meeting_hits, meeting_chunk_ids = _search_meeting_chunks(
            db, user, payload, query_vec,
        )
    if payload.sources in ("all", "documents"):
        document_hits, document_chunk_ids = _search_document_chunks(
            db, user, payload, query_vec,
        )

    # Merge by similarity (desc) and slice to top_k. Each side already
    # came back limited to top_k, so the worst case is 2×top_k input.
    merged = sorted(
        meeting_hits + document_hits,
        key=lambda h: h.similarity,
        reverse=True,
    )[: payload.top_k]

    # Walk the merged list to figure out which IDs *survived* the slice —
    # we only bump access counts for chunks that actually showed up to
    # the user.
    surviving_meeting_ids = [
        h.chunk_id for h in merged if h.source_type == "meeting"
    ]
    surviving_document_ids = [
        h.chunk_id for h in merged if h.source_type == "document"
    ]

    if surviving_meeting_ids or surviving_document_ids:
        now = datetime.now(timezone.utc)
        if surviving_meeting_ids:
            db.query(MeetingChunk).filter(
                MeetingChunk.id.in_(surviving_meeting_ids),
            ).update(
                {
                    MeetingChunk.last_accessed_at: now,
                    MeetingChunk.access_count: MeetingChunk.access_count + 1,
                },
                synchronize_session=False,
            )
        if surviving_document_ids:
            db.query(DocumentChunk).filter(
                DocumentChunk.id.in_(surviving_document_ids),
            ).update(
                {
                    DocumentChunk.last_accessed_at: now,
                    DocumentChunk.access_count: DocumentChunk.access_count + 1,
                },
                synchronize_session=False,
            )
        db.commit()

    # Phase 6B — log one 'search_hit' event per surviving chunk so the
    # 6C reranker can read citation/access patterns. Fire-and-forget;
    # a logging failure must NEVER affect the search response.
    if merged:
        from app.services.importance.access_log import log_chunk_events_batch
        events = []
        for rank, h in enumerate(merged):
            events.append((h.chunk_id, h.source_type, rank))
        log_chunk_events_batch(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            event_type="search_hit",
            chunks=events,
        )

    logger.info(
        "search(org=%s, scope=%s, scope_id=%s, top_k=%d, sources=%s): "
        "%d meeting + %d doc -> %d merged",
        user.organization_id,
        payload.scope, payload.scope_id, payload.top_k, payload.sources,
        len(meeting_hits), len(document_hits), len(merged),
    )
    return SearchResponse(
        query=payload.query,
        scope=payload.scope,
        scope_id=payload.scope_id,
        sources=payload.sources,
        embedding_model=embedder.model,
        hits=merged,
    )


@router.get("/meetings/{meeting_id}/chunks", response_model=MeetingChunksResponse)
def get_meeting_chunks(
    meeting_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
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

    chunks = [_build_meeting_hit(row, similarity=1.0) for row in db.execute(stmt).all()]
    return MeetingChunksResponse(
        meeting_id=meeting.id,
        embedding_status=meeting.embedding_status,
        embedded_at=meeting.embedded_at,
        chunks=chunks,
    )


# ---------------------------------------------------------------------------
# Phase 4E — document chunks inspection. Sibling of the meeting endpoint.
# ---------------------------------------------------------------------------

@router.get(
    "/documents/{kind}/{document_id}/chunks",
    response_model=DocumentChunksResponse,
)
def get_document_chunks(
    kind: str,
    document_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Return every chunk produced for a document, in `chunk_index` order.
    `kind` is `'category'` or `'team'`. Org-scoped: a doc belonging to a
    sibling org is treated as nonexistent (404)."""
    if kind not in ("category", "team"):
        raise HTTPException(status_code=400, detail="kind must be 'category' or 'team'")

    if kind == "category":
        doc = db.execute(
            select(CategoryDocument).where(
                CategoryDocument.id == document_id,
                CategoryDocument.organization_id == user.organization_id,
            )
        ).scalar_one_or_none()
    else:
        doc = db.execute(
            select(TeamDocument).where(
                TeamDocument.id == document_id,
                TeamDocument.organization_id == user.organization_id,
            )
        ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    from sqlalchemy import func
    stmt = (
        select(
            DocumentChunk,
            func.coalesce(CategoryDocument.id, TeamDocument.id).label("document_id"),
            func.coalesce(CategoryDocument.name, TeamDocument.name).label("document_name"),
            Category.id.label("category_id"),
            Category.name.label("category_name"),
            Category.color.label("category_color"),
            Team.id.label("team_id"),
            Team.name.label("team_name"),
        )
        .outerjoin(CategoryDocument, DocumentChunk.category_document_id == CategoryDocument.id)
        .outerjoin(TeamDocument, DocumentChunk.team_document_id == TeamDocument.id)
        .outerjoin(Category, DocumentChunk.category_id == Category.id)
        .outerjoin(Team, DocumentChunk.team_id == Team.id)
        .where(DocumentChunk.organization_id == user.organization_id)
        .order_by(DocumentChunk.chunk_index)
    )
    if kind == "category":
        stmt = stmt.where(DocumentChunk.category_document_id == document_id)
    else:
        stmt = stmt.where(DocumentChunk.team_document_id == document_id)

    chunks = [_build_document_hit(row, similarity=1.0) for row in db.execute(stmt).all()]
    return DocumentChunksResponse(
        document_id=doc.id,
        document_kind=kind,
        document_name=doc.name,
        embedding_status=doc.embedding_status,
        embedded_at=doc.embedded_at,
        chunks=chunks,
    )
