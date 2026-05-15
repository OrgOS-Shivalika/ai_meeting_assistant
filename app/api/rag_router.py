"""Phase 5D — RAG HTTP surface.

Endpoints:

    POST /rag/ask                                — single-shot SSE Q&A
    POST /rag/conversations                      — create
    GET  /rag/conversations                      — list (current user)
    GET  /rag/conversations/{id}                 — detail + runs
    DELETE /rag/conversations/{id}               — delete (cascades runs)
    POST /rag/conversations/{id}/messages        — multi-turn SSE
    GET  /rag/runs/{id}                          — fetch one audit row

Every endpoint is org-scoped via `Depends(get_current_user)`. Cross-org
access returns 404 (never 403) to avoid leaking existence — same
convention as the rest of the codebase.

`/rag/ask` and `/rag/conversations/{id}/messages` both produce SSE.
Internally they share `ask_pipeline.ask_stream`; the router formats
its event dicts into SSE bytes.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.db.models import (
    Category, RagConversation, RagQueryRun, Team, User,
)
from app.dependencies.auth import get_current_user
from app.schemas.rag_api_schema import (
    AskRequest, ConversationCreateRequest, ConversationDetail,
    ConversationSummary, RunDetail, RunSummary,
)
from app.services.rag.ask_pipeline import ask_stream, event_to_sse_bytes
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/rag", tags=["RAG"])


# ---------------------------------------------------------------------------
# Scope validation — mirrors search_router's pattern
# ---------------------------------------------------------------------------

def _validate_scope(db: Session, user: User, scope: str, scope_id: Optional[int]) -> None:
    if scope == "category":
        cat = db.query(Category.id).filter(
            Category.id == scope_id,
            Category.organization_id == user.organization_id,
        ).first()
        if cat is None:
            raise HTTPException(status_code=404, detail="Category not found")
    elif scope == "team":
        team = (
            db.query(Team.id)
            .join(Category, Team.category_id == Category.id)
            .filter(
                Team.id == scope_id,
                Category.organization_id == user.organization_id,
            )
            .first()
        )
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")


# ---------------------------------------------------------------------------
# POST /rag/ask  (and /rag/conversations/{id}/messages — same body)
# ---------------------------------------------------------------------------

def _resolve_scope_for_pipeline(payload: AskRequest):
    """Translate API-level `scope` to the pipeline's
    (requested_scope_type, requested_scope_id) shape. `auto` becomes
    None so the planner decides."""
    if payload.scope == "auto":
        return None, None
    return payload.scope, payload.scope_id


@router.post("/ask")
def ask(
    payload: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Single-shot Q&A. Returns SSE.

    Event sequence: plan, retrieved, token (repeated), citations, done.
    On failure: error followed by done with status='failed'."""
    _validate_scope(db, user, payload.scope, payload.scope_id)

    # Verify conversation_id belongs to this user (if provided)
    if payload.conversation_id is not None:
        conv = db.query(RagConversation).filter(
            RagConversation.id == payload.conversation_id,
            RagConversation.organization_id == user.organization_id,
            RagConversation.user_id == user.id,
        ).first()
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    req_scope, req_scope_id = _resolve_scope_for_pipeline(payload)

    def _generate():
        # Re-acquire the DB session inside the generator. StreamingResponse
        # may outlive the request-scoped one in some servers; safer to own
        # the session here.
        from app.db.database import SessionLocal
        inner_db = SessionLocal()
        try:
            # Translate 'auto' → None so the pipeline uses
            # settings.RAG_RERANK_STRATEGY (current default: legacy_weighted).
            rerank = (
                None if payload.rerank_strategy == "auto"
                else payload.rerank_strategy
            )
            for event in ask_stream(
                inner_db,
                organization_id=user.organization_id,
                user_id=user.id,
                query_text=payload.query,
                requested_scope_type=req_scope,
                requested_scope_id=req_scope_id,
                conversation_id=payload.conversation_id,
                sources=payload.sources,
                top_k_final=payload.top_k,
                rerank_strategy=rerank,
            ):
                yield event_to_sse_bytes(event)
        finally:
            inner_db.close()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx: disable buffering
        },
    )


@router.post("/conversations/{conversation_id}/messages")
def append_message(
    conversation_id: UUID,
    payload: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Multi-turn variant. Same event sequence as /rag/ask; the
    conversation_id from the URL takes precedence over any in the body."""
    conv = db.query(RagConversation).filter(
        RagConversation.id == conversation_id,
        RagConversation.organization_id == user.organization_id,
        RagConversation.user_id == user.id,
    ).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Force the conversation_id from the URL
    payload_dict = payload.model_dump()
    payload_dict["conversation_id"] = conversation_id
    forced = AskRequest(**payload_dict)
    return ask(forced, db=db, user=user)


# ---------------------------------------------------------------------------
# Conversations CRUD
# ---------------------------------------------------------------------------

@router.post("/conversations", response_model=ConversationSummary, status_code=201)
def create_conversation(
    payload: ConversationCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pinned_type = payload.pinned_scope if payload.pinned_scope in ("team", "category", "global") else None
    if pinned_type in ("team", "category"):
        _validate_scope(db, user, pinned_type, payload.pinned_scope_id)
    conv = RagConversation(
        organization_id=user.organization_id,
        user_id=user.id,
        title=payload.title,
        pinned_scope_type=pinned_type,
        pinned_scope_id=payload.pinned_scope_id if pinned_type in ("team", "category") else None,
    )
    db.add(conv); db.commit(); db.refresh(conv)
    return conv


@router.get("/conversations", response_model=List[ConversationSummary])
def list_conversations(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(RagConversation)
        .filter(
            RagConversation.organization_id == user.organization_id,
            RagConversation.user_id == user.id,
        )
        .order_by(RagConversation.updated_at.desc())
        .limit(min(max(limit, 1), 200))
        .all()
    )
    return rows


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = db.query(RagConversation).filter(
        RagConversation.id == conversation_id,
        RagConversation.organization_id == user.organization_id,
        RagConversation.user_id == user.id,
    ).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    runs = (
        db.query(RagQueryRun)
        .filter(RagQueryRun.conversation_id == conv.id)
        .order_by(RagQueryRun.created_at.asc())
        .all()
    )
    return ConversationDetail(
        id=conv.id, title=conv.title,
        pinned_scope_type=conv.pinned_scope_type,
        pinned_scope_id=conv.pinned_scope_id,
        created_at=conv.created_at, updated_at=conv.updated_at,
        runs=[RunSummary.model_validate(r) for r in runs],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = db.query(RagConversation).filter(
        RagConversation.id == conversation_id,
        RagConversation.organization_id == user.organization_id,
        RagConversation.user_id == user.id,
    ).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conv); db.commit()


# ---------------------------------------------------------------------------
# Run inspector (debug + eval)
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Full audit row for one query. Used by the 5F eval harness and
    by debugging UIs. Org-scoped: cross-org returns 404."""
    row = db.query(RagQueryRun).filter(
        RagQueryRun.id == run_id,
        RagQueryRun.organization_id == user.organization_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


# ---------------------------------------------------------------------------
# Phase 6B — citation click beacon
# ---------------------------------------------------------------------------

@router.post("/runs/{run_id}/citations/{citation_index}/click", status_code=204)
def click_citation(
    run_id: UUID,
    citation_index: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Record a citation-chip click. Frontend fires this just before
    navigating to the source. Non-blocking from the client's
    perspective — used by 6C as the strongest "this chunk was useful"
    signal.

    Resolves chunk_id from the run's stored citations JSONB so the
    client only needs to send the citation index, not the chunk_id.
    Returns 204 even when the citation index isn't in the run — clicks
    are best-effort signals, no need to error a frontend nav over a
    stale link.
    """
    row = db.query(RagQueryRun).filter(
        RagQueryRun.id == run_id,
        RagQueryRun.organization_id == user.organization_id,
    ).first()
    if row is None:
        # 404 here so a malicious user can't probe other orgs' run ids.
        raise HTTPException(status_code=404, detail="Run not found")

    citations = row.citations or []
    target = next(
        (c for c in citations if c.get("index") == citation_index),
        None,
    )
    if target is None or not target.get("chunk_id"):
        # Citation index not present — silently no-op (still 204).
        return

    from app.services.importance.access_log import log_citation_click
    log_citation_click(
        db,
        organization_id=user.organization_id,
        run_id=run_id,
        chunk_id=UUID(target["chunk_id"]),
        citation_index=citation_index,
        user_id=user.id,
    )
