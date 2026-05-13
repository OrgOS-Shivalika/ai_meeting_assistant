"""Team-document ingestion Celery task.

Phase 4C — real body. Sibling of `document_tasks.process_document`; both
funnel into `document_ingest._ingest_document_sync` so the
parse/chunk/embed pipeline lives in one place.
"""
from __future__ import annotations

from app.celery_app import celery
from app.celery_tasks.document_ingest import _ingest_document_sync
from app.db.database import SessionLocal
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@celery.task(name="meeting_ai.process_team_document", bind=True)
def process_team_document(self, document_id: str) -> dict:
    """Ingest a single TeamDocument. Never raises — failures are
    recorded on the row via `embedding_status='failed'` + `error_message`."""
    logger.info(
        "Celery task started: process_team_document(document_id=%s)", document_id,
    )
    db = SessionLocal()
    try:
        return _ingest_document_sync(db, "team", document_id)
    finally:
        db.close()
