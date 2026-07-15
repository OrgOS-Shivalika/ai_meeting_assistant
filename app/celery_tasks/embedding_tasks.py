"""Phase 2C — embedding pipeline as a Celery task.

The meeting pipeline (`process_meeting`) emits a completed meeting row.
Once that's done, this task picks the meeting up, chunks its transcript,
embeds the chunks, and writes them to `meeting_chunks`.

Design notes:

- **Decoupled lifecycle.** `meeting.status` ("completed" / "failed") stays
  owned by the main pipeline. We only mutate `meeting.embedding_status`
  and `meeting.embedded_at` here, so an embedding failure cannot mark a
  meeting itself as broken.
- **Idempotent.** Re-running for the same meeting deletes its existing
  chunks in the same transaction as the new insert, so a shrinking
  chunk count doesn't leave stale rows behind. The
  `(organization_id, meeting_id, chunk_index)` unique constraint
  guarantees no partial inserts can survive a crash.
- **Single transaction per meeting.** The chunker is in-memory; the
  embedder is the one external call. We pull all vectors first, then
  open the DB transaction, so partial chunks are never persisted.
- **Reusable in 2E (backfill).** `_embed_meeting_sync(db, meeting)` is
  the worker function; the Celery task is a thin wrapper that owns a
  session. The backfill script calls the sync function directly.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.celery_app import celery
from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import Meeting, MeetingChunk
from app.services.chunker import TranscriptChunker
from app.services.embedder import Embedder
from app.utils.enums import EmbeddingStatus
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _embed_meeting_sync(
    db: Session,
    meeting: Meeting,
    *,
    chunker: TranscriptChunker | None = None,
    embedder: Embedder | None = None,
) -> dict:
    """Chunk + embed a single meeting. Caller owns the session lifecycle.

    Returns a stats dict with chunk count and status. Never re-raises —
    failures are logged and the meeting's `embedding_status` is flipped
    to `failed` for visibility.

    The `chunker` and `embedder` kwargs exist so the backfill script and
    tests can inject stubbed instances (e.g. to skip the OpenAI call).
    """
    meeting_id = meeting.id
    transcript_raw = meeting.transcript_raw
    if not transcript_raw:
        logger.info(
            "embed_meeting(%s): no transcript_raw — marking embedding_status=skipped",
            meeting_id,
        )
        meeting.embedding_status = EmbeddingStatus.SKIPPED
        db.commit()
        return {"status": "skipped", "meeting_id": meeting_id, "chunks": 0}

    # Flip to processing before we do anything heavy. A separate commit
    # so observers see we picked it up, even if chunking takes a moment.
    meeting.embedding_status = EmbeddingStatus.PROCESSING
    db.commit()

    chunker = chunker or TranscriptChunker()
    embedder = embedder or Embedder()
    started = time.monotonic()

    try:
        chunks = chunker.chunk(transcript_raw)
        if not chunks:
            logger.info(
                "embed_meeting(%s): chunker produced 0 chunks — nothing to embed",
                meeting_id,
            )
            meeting.embedding_status = EmbeddingStatus.EMBEDDED
            meeting.embedded_at = datetime.now(timezone.utc)
            db.commit()
            return {"status": "embedded", "meeting_id": meeting_id, "chunks": 0}

        # External call first. If embedding fails we never touched the
        # meeting_chunks table.
        texts = [c.text for c in chunks]
        vectors = embedder.embed(texts)
        if len(vectors) != len(chunks):
            raise RuntimeError(
                f"embed_meeting({meeting_id}): vector/chunk count mismatch "
                f"({len(vectors)} vectors for {len(chunks)} chunks)"
            )

        # Single transaction: clear prior chunks for this meeting, insert
        # the fresh batch. The unique constraint
        # (organization_id, meeting_id, chunk_index) guarantees consistency.
        db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == meeting.organization_id,
            MeetingChunk.meeting_id == meeting_id,
        ).delete(synchronize_session=False)

        for chunk, vector in zip(chunks, vectors):
            db.add(
                MeetingChunk(
                    organization_id=meeting.organization_id,
                    meeting_id=meeting_id,
                    category_id=meeting.category_id,
                    team_id=meeting.team_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    speakers=chunk.speakers or None,
                    start_timestamp=chunk.start_timestamp,
                    end_timestamp=chunk.end_timestamp,
                    embedding=vector,
                    embedding_model=embedder.model,
                    # Phase 2 doesn't score chunks yet — leave the
                    # knowledge-metadata columns at their schema defaults
                    # (knowledge_version=1, access_count=0). Phase 3+
                    # extractors will fill the scores in.
                    created_from_meeting_id=meeting_id,
                )
            )

        meeting.embedding_status = EmbeddingStatus.EMBEDDED
        meeting.embedded_at = datetime.now(timezone.utc)
        db.commit()

        duration_ms = int((time.monotonic() - started) * 1000)
        total_tokens = sum(c.token_count for c in chunks)
        logger.info(
            "embed_meeting(%s): inserted %d chunks tokens=%d model=%s duration_ms=%d",
            meeting_id,
            len(chunks),
            total_tokens,
            embedder.model,
            duration_ms,
        )

        # Phase 3 fan-out: kick the graph extractor. Best-effort — same
        # contract as the meeting-pipeline -> embed_meeting handoff in
        # Phase 2. A graph dispatch failure must never invalidate the
        # embedding success we just committed.
        try:
            from app.celery_tasks.graph_tasks import dispatch_extract_graph
            dispatch_extract_graph(meeting_id)
        except Exception as graph_err:
            logger.error(
                "embed_meeting(%s): failed to dispatch graph extraction: %s",
                meeting_id, graph_err,
            )

        return {
            "status": "embedded",
            "meeting_id": meeting_id,
            "chunks": len(chunks),
            "tokens": total_tokens,
            "model": embedder.model,
            "duration_ms": duration_ms,
        }

    except Exception as exc:
        db.rollback()
        # Flag the meeting as failed-to-embed but DO NOT touch
        # `meeting.status`. The meeting itself is still completed; only
        # its semantic-search side is broken.
        try:
            meeting.embedding_status = EmbeddingStatus.FAILED
            db.commit()
        except Exception:
            db.rollback()
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.error(
            "embed_meeting(%s) failed after %dms: %s",
            meeting_id, duration_ms, exc, exc_info=True,
        )
        return {
            "status": "failed",
            "meeting_id": meeting_id,
            "error": str(exc),
            "duration_ms": duration_ms,
        }


@celery.task(name="meeting_ai.embed_meeting", bind=True)
def embed_meeting(self, meeting_id: int) -> dict:
    """Celery wrapper. Loads the meeting, calls the sync worker, returns
    a status dict.

    We don't re-raise on failure — `_embed_meeting_sync` already records
    the failure on the meeting row, and re-raising would trigger Celery
    auto-retry (we don't want that; chunking failures are usually
    deterministic until the input changes)."""
    logger.info("Celery task started: embed_meeting(meeting_id=%s)", meeting_id)
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            logger.error("embed_meeting: meeting %s not found", meeting_id)
            return {"status": "missing", "meeting_id": meeting_id}
        return _embed_meeting_sync(db, meeting)
    finally:
        db.close()


def dispatch_embed_meeting(meeting_id: int) -> None:
    """Single entry point used by the meeting pipeline.

    Picks the right execution path:
      - `USE_CELERY=true`  → `embed_meeting.delay(meeting_id)` (fire-and-forget)
      - `USE_CELERY=false` → run inline on a fresh session in the same thread

    Either way this never raises; embedding is best-effort relative to
    the meeting pipeline."""
    try:
        if settings.USE_CELERY:
            embed_meeting.delay(meeting_id)
            logger.info("embed_meeting dispatched to Celery for meeting %s", meeting_id)
            return
        # Inline fallback for dev boxes without a broker.
        db = SessionLocal()
        try:
            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            if not meeting:
                logger.error(
                    "dispatch_embed_meeting: meeting %s not found", meeting_id
                )
                return
            _embed_meeting_sync(db, meeting)
        finally:
            db.close()
    except Exception as exc:
        # Never let a dispatch failure poison the caller.
        logger.error(
            "dispatch_embed_meeting(%s) crashed: %s", meeting_id, exc, exc_info=True
        )
