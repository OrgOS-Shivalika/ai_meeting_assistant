"""Phase 6B — chunk access + citation click event logger.

Safe-fire helpers that record events into the append-only event tables.
**Every function in this module swallows its own exceptions.** A
logging failure must NEVER poison the calling code path:

  - A search query that wrote 10 chunks should return 10 hits to the
    user even if writing 10 access events failed.
  - A RAG ask_stream that streamed an answer should emit the `done`
    event even if `rag_cited` events couldn't be written.

So every helper here is a fire-and-forget. Errors are logged to
`logger`; the caller never sees an exception.

The three log_* helpers write to `ChunkAccessEvent`; `log_citation_click`
writes to `CitationClickEvent`.
"""
from __future__ import annotations

import logging
from typing import Iterable, Literal, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import ChunkAccessEvent, CitationClickEvent

logger = logging.getLogger(__name__)

ChunkKind = Literal["meeting", "document"]
EventType = Literal["search_hit", "rag_retrieve", "rag_cited"]


def log_chunk_event(
    db: Session,
    *,
    organization_id: UUID,
    chunk_id: UUID,
    chunk_kind: ChunkKind,
    event_type: EventType,
    run_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    rank_position: Optional[int] = None,
) -> None:
    """Insert one access event. Never raises."""
    try:
        db.add(ChunkAccessEvent(
            organization_id=organization_id,
            chunk_id=chunk_id,
            chunk_kind=chunk_kind,
            event_type=event_type,
            run_id=run_id,
            user_id=user_id,
            rank_position=rank_position,
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(
            "access_log: failed to write %s event (chunk=%s): %s",
            event_type, chunk_id, e,
        )


def log_chunk_events_batch(
    db: Session,
    *,
    organization_id: UUID,
    user_id: Optional[UUID],
    event_type: EventType,
    chunks: Iterable[tuple[UUID, ChunkKind, Optional[int]]],
    run_id: Optional[UUID] = None,
) -> int:
    """Bulk-insert event rows for a list of (chunk_id, chunk_kind,
    rank_position) tuples. Single commit, fewer round-trips than calling
    `log_chunk_event` N times. Never raises; returns count written
    (0 on failure)."""
    rows = list(chunks)
    if not rows:
        return 0
    try:
        db.bulk_save_objects([
            ChunkAccessEvent(
                organization_id=organization_id,
                chunk_id=chunk_id,
                chunk_kind=chunk_kind,
                event_type=event_type,
                run_id=run_id,
                user_id=user_id,
                rank_position=rank,
            )
            for chunk_id, chunk_kind, rank in rows
        ])
        db.commit()
        return len(rows)
    except Exception as e:
        db.rollback()
        logger.warning(
            "access_log: batch %s insert failed (%d rows): %s",
            event_type, len(rows), e,
        )
        return 0


def log_citation_click(
    db: Session,
    *,
    organization_id: UUID,
    run_id: UUID,
    chunk_id: UUID,
    citation_index: int,
    user_id: Optional[UUID] = None,
) -> bool:
    """Record one citation-chip click. Returns True on success. Never raises."""
    try:
        db.add(CitationClickEvent(
            organization_id=organization_id,
            run_id=run_id,
            chunk_id=chunk_id,
            user_id=user_id,
            citation_index=citation_index,
        ))
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.warning(
            "access_log: citation click insert failed (run=%s idx=%d): %s",
            run_id, citation_index, e,
        )
        return False
