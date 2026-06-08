"""Live-transcript persistence helper.

Replaces the O(n^2) read-modify-write pattern that previously lived
inline in both `app/api/webhooks/recall_webhook.py` and
`app/api/ws_router.py`. Two improvements stacked:

1. Server-side string concatenation (single UPDATE roundtrip; no
   read-then-write). Postgres still pays O(n) per write to rewrite
   the TEXT column, but the FastAPI process avoids buffering the
   whole accumulated transcript in Python on every utterance.

2. Async dispatch — callers schedule this via `asyncio.to_thread`
   so the synchronous SQLAlchemy commit does not block the FastAPI
   event loop. Other webhooks (transcripts, bot lifecycle, frontend
   WS broadcasts) stay responsive while the save runs in a worker.

A Tier 3 follow-up would split transcript lines into their own table
for O(1) inserts — out of scope for this fix because it touches the
post-meeting consumer (process_meeting reads `meeting.transcript`).
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.db.database import SessionLocal

logger = logging.getLogger(__name__)


def save_transcript_line_sync(meeting_id: int, formatted_line: str) -> None:
    """Append a single line to `meetings.transcript`, server-side.

    Synchronous; intended to be invoked via `asyncio.to_thread` from
    async handlers. The UPDATE uses Postgres string concatenation so
    we do NOT have to read the existing transcript into Python first.
    """
    db = SessionLocal()
    try:
        result = db.execute(
            text(
                """
                UPDATE meetings
                SET transcript = CASE
                    WHEN transcript IS NULL OR transcript = '' THEN :line
                    ELSE transcript || E'\n' || :line
                END
                WHERE id = :mid
                """
            ),
            {"line": formatted_line, "mid": meeting_id},
        )
        if result.rowcount == 0:
            logger.warning(
                f"[TRANSCRIPT] meeting {meeting_id} not found while saving line"
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            f"[TRANSCRIPT] DB error saving line for meeting {meeting_id}: {exc}",
            exc_info=True,
        )
    finally:
        db.close()


def schedule_transcript_save(meeting_id: int, formatted_line: str) -> None:
    """Fire-and-forget the save on a worker thread so the calling
    async handler can return immediately.

    Callers that need to await completion (rare — typically only tests)
    should call `save_transcript_line_sync` directly.
    """
    asyncio.create_task(
        asyncio.to_thread(save_transcript_line_sync, meeting_id, formatted_line)
    )
