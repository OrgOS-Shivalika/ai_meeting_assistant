"""Document ingestion tasks.

Phase 1 stub: marks the row as `ready` so the UI can show a green badge.
Phase 2 replaces the body with: download from S3 -> sniff type -> parse to
text -> chunk (800/100) -> embed -> write to category_chunks /
category_embeddings -> set status='ready'. The contract — accept doc_id, mark
status terminally — stays the same. Routes will not need to change.
"""

from app.celery_app import celery
from app.db.database import SessionLocal
from app.db.models import CategoryDocument
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@celery.task(name="meeting_ai.process_document", bind=True)
def process_document(self, document_id: str) -> dict:
    logger.info("Celery task started: process_document(document_id=%s)", document_id)

    db = SessionLocal()
    try:
        doc = db.query(CategoryDocument).filter(CategoryDocument.id == document_id).first()
        if not doc:
            logger.error("Document %s not found", document_id)
            return {"status": "missing", "document_id": document_id}

        # Phase 1 stub — see module docstring.
        doc.status = "ready"
        doc.error_message = None
        db.commit()

        return {"status": "ready", "document_id": document_id}

    except Exception as exc:
        logger.error("process_document(%s) failed: %s", document_id, exc)
        try:
            db.rollback()
            doc = db.query(CategoryDocument).filter(CategoryDocument.id == document_id).first()
            if doc:
                doc.status = "failed"
                doc.error_message = str(exc)[:1000]
                db.commit()
        except Exception:
            pass
        return {"status": "failed", "document_id": document_id, "error": str(exc)}

    finally:
        db.close()
