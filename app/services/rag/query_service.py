"""Database logic for the RAG HTTP surface.

Extracted from ``app/api/rag_router.py`` so the router stays a thin
transport layer. Functions take the SQLAlchemy ``Session`` plus the current
user and raise ``HTTPException`` for ownership / scope failures — mirroring
the convention in ``category_service`` and keeping behaviour identical to the
previous in-router helpers.

Cross-org access returns 404 (never 403) to avoid leaking existence — same
convention as the rest of the codebase.

Streaming (SSE) endpoints deliberately keep their own DB session lifecycle
inside the response generator; only the cleanly-separable query/persistence
steps are extracted here.
"""
from __future__ import annotations

from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import (
    Category, Meeting, RagConversation, RagQueryRun, Team, User,
)
from app.schemas.rag_api_schema import (
    AskLivePrefetchResponse, ConversationCreateRequest, PrefetchedFact,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# Scope validation — mirrors search_service's pattern
# ---------------------------------------------------------------------------

def validate_scope(db: Session, user: User, scope: str, scope_id: Optional[int]) -> None:
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


def scope_from_meeting(
    db: Session, *, organization_id, meeting_id,
) -> Tuple[Optional[str], Optional[int]]:
    """Phase 9.1 — when the caller passes `meeting_id` and no explicit
    scope, resolve the meeting's (category_id, team_id) and translate
    to a pipeline scope. team_id wins (more specific); falls back to
    category_id; falls back to (None, None) if the meeting has neither
    set. Cross-org meetings return (None, None) silently."""
    m = (
        db.query(Meeting)
        .filter(
            Meeting.id == meeting_id,
            Meeting.organization_id == organization_id,
        )
        .first()
    )
    if m is None:
        return None, None
    if m.team_id is not None:
        return "team", m.team_id
    if m.category_id is not None:
        return "category", m.category_id
    return None, None


def get_meeting_or_404(db: Session, user: User, meeting_id: int) -> Meeting:
    """Fetch a meeting scoped to the user's org. Cross-org 404."""
    m = db.query(Meeting).filter(
        Meeting.id == meeting_id,
        Meeting.organization_id == user.organization_id,
    ).first()
    if m is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return m


# ---------------------------------------------------------------------------
# Memory Phase 3 — long-term block (raw DB reads via LongTermMemory)
# ---------------------------------------------------------------------------

def build_long_term_block(
    db: Session, *, organization_id, category_id, team_id,
) -> str:
    """The full record of recent meetings in this scope: their summaries +
    their tasks. Complements the short-term distilled facts (curated bullets)
    with the raw texture of "what actually happened."

    No days filter — long-term reaches EVERY meeting in this scope, not just
    the recent 60 days. The prompt formatter itself caps output at 3500 chars,
    so a large scope just means "newest N summaries that fit"; older meetings
    are still reachable via chunk RAG and typed lookups.
    """
    from app.services.memory.long_term import LongTermMemory
    from app.services.memory.prompt_blocks import render_long_term_block

    summaries = LongTermMemory.recent_summaries(
        db,
        organization_id=organization_id,
        category_id=category_id,
        team_id=team_id,
        days=None,
        limit=25,  # formatter truncates on chars, this is a safety valve
    )
    tasks = LongTermMemory.tasks_in_scope(
        db,
        organization_id=organization_id,
        category_id=category_id,
        team_id=team_id,
        days=None,
        limit=50,
    )
    long_term_block = render_long_term_block(summaries, tasks)
    if long_term_block:
        logger.info(
            "💭 ask-live: long-term block ready (%d summaries, %d tasks, %d chars)",
            len(summaries), len(tasks), len(long_term_block),
        )
    return long_term_block


# ---------------------------------------------------------------------------
# ask-live prefetch
# ---------------------------------------------------------------------------

def prefetch_facts(db: Session, user: User, meeting_id: int) -> AskLivePrefetchResponse:
    """Pre-warm the in-meeting panel with the 5 most-recently-referenced
    facts for this meeting's (team, category) scope. Used on panel open
    to show context chips before the user types — feels instant."""
    m = get_meeting_or_404(db, user, meeting_id)

    from app.services.memory.access import MemoryAccess
    facts = MemoryAccess.search(
        db,
        organization_id=user.organization_id,
        query="",                       # empty -> recency order
        category_id=m.category_id,
        team_id=m.team_id,
        window="short_term",
        limit=5,
        bump=False,                     # prefetch != real consumption
    )

    # Resolve source meeting titles in ONE batched query for chip labels.
    source_ids = {f.source_meeting_id for f in facts if f.source_meeting_id}
    title_map: dict[int, str] = {}
    if source_ids:
        rows = db.query(Meeting.id, Meeting.title).filter(
            Meeting.id.in_(source_ids),
            Meeting.organization_id == user.organization_id,
        ).all()
        title_map = {r.id: r.title for r in rows}

    scope_type = "team" if m.team_id else ("category" if m.category_id else None)
    scope_id = m.team_id or m.category_id

    return AskLivePrefetchResponse(
        scope_type=scope_type,
        scope_id=scope_id,
        facts=[
            PrefetchedFact(
                id=f.id,
                fact=f.fact,
                fact_type=f.fact_type,
                subject=f.subject,
                source_meeting_id=f.source_meeting_id,
                source_meeting_title=title_map.get(f.source_meeting_id),
                last_referenced_at=f.last_referenced_at,
            )
            for f in facts
        ],
    )


# ---------------------------------------------------------------------------
# Conversations CRUD
# ---------------------------------------------------------------------------

def get_owned_conversation(db: Session, user: User, conversation_id) -> RagConversation:
    conv = db.query(RagConversation).filter(
        RagConversation.id == conversation_id,
        RagConversation.organization_id == user.organization_id,
        RagConversation.user_id == user.id,
    ).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


def create_conversation(
    db: Session, user: User, payload: ConversationCreateRequest,
) -> RagConversation:
    pinned_type = payload.pinned_scope if payload.pinned_scope in ("team", "category", "global") else None
    if pinned_type in ("team", "category"):
        validate_scope(db, user, pinned_type, payload.pinned_scope_id)
    conv = RagConversation(
        organization_id=user.organization_id,
        user_id=user.id,
        title=payload.title,
        pinned_scope_type=pinned_type,
        pinned_scope_id=payload.pinned_scope_id if pinned_type in ("team", "category") else None,
    )
    db.add(conv); db.commit(); db.refresh(conv)
    return conv


def list_conversations(db: Session, user: User, limit: int) -> List[RagConversation]:
    return (
        db.query(RagConversation)
        .filter(
            RagConversation.organization_id == user.organization_id,
            RagConversation.user_id == user.id,
        )
        .order_by(RagConversation.updated_at.desc())
        .limit(min(max(limit, 1), 200))
        .all()
    )


def get_conversation_with_runs(
    db: Session, user: User, conversation_id,
) -> Tuple[RagConversation, List[RagQueryRun]]:
    conv = get_owned_conversation(db, user, conversation_id)
    runs = (
        db.query(RagQueryRun)
        .filter(RagQueryRun.conversation_id == conv.id)
        .order_by(RagQueryRun.created_at.asc())
        .all()
    )
    return conv, runs


def delete_conversation(db: Session, user: User, conversation_id) -> None:
    conv = get_owned_conversation(db, user, conversation_id)
    db.delete(conv); db.commit()


# ---------------------------------------------------------------------------
# Run inspector (debug + eval)
# ---------------------------------------------------------------------------

def get_run_or_404(db: Session, user: User, run_id) -> RagQueryRun:
    """Full audit row for one query. Org-scoped: cross-org returns 404."""
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

def record_citation_click(
    db: Session, user: User, run_id, citation_index: int,
) -> None:
    """Record a citation-chip click.

    Resolves chunk_id from the run's stored citations JSONB so the client
    only needs to send the citation index, not the chunk_id. Silently
    no-ops when the citation index isn't in the run — clicks are best-effort
    signals, no need to error a frontend nav over a stale link.
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
