"""Phase 2D / 4E search API.

POST /search                       — semantic search across the user's org.
GET  /meetings/{meeting_id}/chunks — inspection of a meeting's embedded chunks.
GET  /documents/{kind}/{doc_id}/chunks
                                   — inspection of a document's chunks.

Both list endpoints are org-scoped from `get_current_user`. The `scope`
body parameter narrows further (to a category or team within the org); we
validate the scope belongs to the user's org before running the query so
a forged id from a sibling tenant returns 404, not silently empty hits.

DB logic lives in `app.services.search_service`; this module is the thin
transport layer plus embedder management.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.schemas.search_schema import (
    DocumentChunksResponse,
    MeetingChunksResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from app.services import search_service
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    search_service.validate_scope(db, user, payload.scope, payload.scope_id)

    embedder = _get_embedder()
    try:
        query_vec = embedder.embed([payload.query])[0]
    except RuntimeError as exc:
        logger.error("Embedder unavailable for search: %s", exc)
        raise HTTPException(status_code=503, detail="Search backend unavailable")

    merged: list[SearchHit] = search_service.search_chunks(db, user, payload, query_vec)

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
    meeting, chunks = search_service.get_meeting_chunks(db, user, meeting_id)
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

    doc, chunks = search_service.get_document_chunks(db, user, kind, document_id)
    return DocumentChunksResponse(
        document_id=doc.id,
        document_kind=kind,
        document_name=doc.name,
        embedding_status=doc.embedding_status,
        embedded_at=doc.embedded_at,
        chunks=chunks,
    )
