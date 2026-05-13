"""Category-document ingestion Celery task.

Phase 4C — real body. Delegates the heavy lifting to
`document_ingest._ingest_document_sync` so the team-document task can
share exactly the same parse + chunk + embed + persist pipeline.

Naming-only quirk: we keep the legacy task name `meeting_ai.process_document`
so existing routers don't have to be rewritten. The function is now
genuinely doing the work the Phase 1 stub promised.
"""
from __future__ import annotations

from app.celery_app import celery
from app.celery_tasks.document_ingest import _ingest_document_sync
from app.db.database import SessionLocal
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@celery.task(name="meeting_ai.process_document", bind=True)
def process_document(self, document_id: str) -> dict:
    """Ingest a single CategoryDocument. Never raises — failures are
    recorded on the row via `embedding_status='failed'` + `error_message`."""
    logger.info("Celery task started: process_document(document_id=%s)", document_id)
    db = SessionLocal()
    try:
        return _ingest_document_sync(db, "category", document_id)
    finally:
        db.close()
