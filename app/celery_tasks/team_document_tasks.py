"""Team-document ingestion tasks.

Phase 1 stub: marks the row as `ready` so the UI shows the green badge.
Phase 2 replaces the body with: download from S3 -> sniff type -> parse to
text -> chunk -> embed -> write to team_chunks / team_embeddings -> set
status='ready'. The contract (accept doc_id, mark status terminally) stays
the same — routes will not need to change.
"""

from app.celery_app import celery
from app.db.database import SessionLocal
from app.db.models import TeamDocument
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@celery.task(name="meeting_ai.process_team_document", bind=True)
def process_team_document(self, document_id: str) -> dict:
    logger.info("Celery task started: process_team_document(document_id=%s)", document_id)

    db = SessionLocal()
    try:
        doc = db.query(TeamDocument).filter(TeamDocument.id == document_id).first()
        if not doc:
            logger.error("Team document %s not found", document_id)
            return {"status": "missing", "document_id": document_id}

        doc.status = "ready"
        doc.error_message = None
        db.commit()

        return {"status": "ready", "document_id": document_id}

    except Exception as exc:
        logger.error("process_team_document(%s) failed: %s", document_id, exc)
        try:
            db.rollback()
            doc = db.query(TeamDocument).filter(TeamDocument.id == document_id).first()
            if doc:
                doc.status = "failed"
                doc.error_message = str(exc)[:1000]
                db.commit()
        except Exception:
            pass
        return {"status": "failed", "document_id": document_id, "error": str(exc)}

    finally:
        db.close()
