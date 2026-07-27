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

DB logic lives in `app.services.rag.query_service`; this module is the
thin transport layer plus the SSE streaming wiring (whose generators own
their own DB session lifecycle deliberately).
"""
from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.dependencies.auth import get_current_user
from app.schemas.rag_api_schema import (
    AskLivePrefetchResponse, AskLiveRequest, AskRequest,
    ConversationCreateRequest, ConversationDetail, ConversationSummary,
    RunDetail, RunSummary,
)
from app.services.rag import query_service
from app.services.rag.ask_pipeline import ask_stream, event_to_sse_bytes
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/rag", tags=["RAG"])


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


def _build_live_state_block(meeting_id_str: str) -> str:
    """Memory Phase 2 — format the in-process MeetingState into a text
    block the synthesizer can prepend to the answer context.

    Returns "" when:
      - No state exists (meeting never had live cognition fire)
      - State exists but has no rolling summary AND no live tasks AND
        no live decisions (nothing useful to inject)

    Reads from `state_store._states` directly via get_state — does NOT
    invent state for unknown meetings (get_state has a side effect of
    creating empty state otherwise). Falls back gracefully on any error.
    """
    from app.services.meeting_memory.meeting_state_store import state_store

    state = state_store._states.get(meeting_id_str)
    if state is None:
        return ""

    lines: list[str] = []

    if state.summary:
        lines.append(f"Rolling summary so far: {state.summary}")

    # Live tasks — show up to 10 most-recent. "Most recent" via insertion
    # order on the dict (Python preserves it).
    if state.active_tasks:
        tasks = list(state.active_tasks.values())[-10:]
        lines.append("Tasks captured in this meeting:")
        for t in tasks:
            owner = getattr(t, "owner", None) or "unassigned"
            due = (
                getattr(t, "due_date", None)
                or getattr(t, "deadline", None)
                or "no date stated"
            )
            status = getattr(t, "status", "detected")
            lines.append(f"  - {t.task} (owner: {owner}, due: {due}, status: {status})")

    if state.active_decisions:
        decisions = list(state.active_decisions.values())[-10:]
        lines.append("Decisions captured in this meeting:")
        for d in decisions:
            text = getattr(d, "decision", None) or str(d)
            decided_by = getattr(d, "decided_by", None) or "unspecified"
            rev = getattr(d, "reversibility", None) or "unspecified"
            lines.append(f"  - {text} (decided by: {decided_by}, reversibility: {rev})")

    if not lines:
        return ""

    return (
        "=== CURRENT MEETING — LIVE STATE (happening right now) ===\n"
        "This is what's being said in the meeting the user is asking from.\n"
        "Treat as the freshest signal. NOT citable.\n"
        + "\n".join(lines)
    )


@router.post("/ask")
def ask(
    payload: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Single-shot Q&A. Returns SSE.

    Event sequence: plan, retrieved, token (repeated), citations, done.
    On failure: error followed by done with status='failed'."""
    query_service.validate_scope(db, user, payload.scope, payload.scope_id)

    # Verify conversation_id belongs to this user (if provided)
    if payload.conversation_id is not None:
        query_service.get_owned_conversation(db, user, payload.conversation_id)

    req_scope, req_scope_id = _resolve_scope_for_pipeline(payload)
    # Phase 9.1 — when scope='auto' but a meeting_id is supplied, pin
    # the pipeline to that meeting's category/team. Explicit scope
    # (set above) wins; this only kicks in when scope was 'auto'.
    if req_scope is None and payload.meeting_id is not None:
        m_scope, m_scope_id = query_service.scope_from_meeting(
            db, organization_id=user.organization_id,
            meeting_id=payload.meeting_id,
        )
        if m_scope is not None:
            req_scope, req_scope_id = m_scope, m_scope_id

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


# ---------------------------------------------------------------------------
# Memory Phase 2 — in-meeting Q&A side-panel
#
# /ask-live is a thin pre-scoped wrapper around ask_stream:
#   - meeting_id is required (the panel always has it)
#   - scope is auto-derived from the meeting's (team, category)
#   - everything else (planner, retrieval, memory wire-in already
#     baked into ask_stream from Phase 1, synth) is shared with /ask
#
# /ask-live/prefetch returns 5 recent same-scope facts so the panel
# can render context chips on open without a streaming round-trip.
# ---------------------------------------------------------------------------


@router.post("/ask-live")
def ask_live(
    payload: AskLiveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """In-meeting panel ask — SSE, same event shape as /rag/ask.

    Reuses ask_stream entirely; the only difference is scope is pinned
    from `meeting_id` so the panel doesn't have to know about scope
    mechanics. The memory wire-in inside ask_stream (added in Phase 1)
    automatically picks up prior facts for this meeting's scope.
    """
    # Cross-org 404 — match the convention in /rag/ask.
    m = query_service.get_meeting_or_404(db, user, payload.meeting_id)

    scope_type, scope_id = query_service.scope_from_meeting(
        db, organization_id=user.organization_id,
        meeting_id=payload.meeting_id,
    )

    # Memory Phase 2 — short-term layer. When the meeting is still in
    # progress, the freshest signal is what was just said — held in the
    # in-process MeetingState (rolling summary + live tasks + live
    # decisions). Format it into a block that the synthesizer renders
    # ABOVE prior facts and chunks. For completed meetings this is "".
    live_block = ""
    if m.status in ("processing", "in_progress", "active"):
        try:
            live_block = _build_live_state_block(str(m.id))
        except Exception as exc:
            logger.warning("ask-live: live state injection skipped: %s", exc)

    # Memory Phase 3 — long-term layer. Complements the short-term
    # distilled facts with the raw texture of "what actually happened."
    # Wrapped non-fatal.
    long_term_block = ""
    try:
        long_term_block = query_service.build_long_term_block(
            db,
            organization_id=user.organization_id,
            category_id=m.category_id,
            team_id=m.team_id,
        )
    except Exception as exc:
        logger.warning("ask-live: long-term injection skipped: %s", exc)

    def _generate():
        from app.db.database import SessionLocal
        inner_db = SessionLocal()
        try:
            for event in ask_stream(
                inner_db,
                organization_id=user.organization_id,
                user_id=user.id,
                query_text=payload.query,
                requested_scope_type=scope_type,
                requested_scope_id=scope_id,
                conversation_id=None,
                sources="meetings",  # in-meeting panel = meeting context only
                top_k_final=payload.top_k_chunks,
                rerank_strategy=None,  # use settings default (recency-tuned)
                live_state_block=live_block,
                long_term_block=long_term_block,
            ):
                yield event_to_sse_bytes(event)
        finally:
            inner_db.close()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/ask-live/prefetch", response_model=AskLivePrefetchResponse)
def ask_live_prefetch(
    meeting_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Pre-warm the in-meeting panel with the 5 most-recently-referenced
    facts for this meeting's (team, category) scope. Used on panel open
    to show context chips before the user types — feels instant."""
    return query_service.prefetch_facts(db, user, meeting_id)


@router.post("/conversations/{conversation_id}/messages")
def append_message(
    conversation_id: UUID,
    payload: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Multi-turn variant. Same event sequence as /rag/ask; the
    conversation_id from the URL takes precedence over any in the body."""
    query_service.get_owned_conversation(db, user, conversation_id)

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
    return query_service.create_conversation(db, user, payload)


@router.get("/conversations", response_model=List[ConversationSummary])
def list_conversations(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return query_service.list_conversations(db, user, limit)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv, runs = query_service.get_conversation_with_runs(db, user, conversation_id)
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
    query_service.delete_conversation(db, user, conversation_id)


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
    return query_service.get_run_or_404(db, user, run_id)


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
    """
    query_service.record_citation_click(db, user, run_id, citation_index)
