"""Document upload routes — category-scoped (Phase 1D).

Async-first: the HTTP request handler streams the file to S3/MinIO and
immediately enqueues a Celery task for downstream processing. The response
returns as soon as the storage write succeeds; chunking / embedding (Phase 2)
will run on the worker without blocking the API.
"""

from __future__ import annotations

import os
import uuid
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.config.settings import settings
from app.db.models import CategoryDocument
from app.dependencies.auth import get_current_user
from app.schemas.document_schema import CategoryDocumentSchema
from app.services import document_service
from app.services.storage_service import storage, StorageNotConfigured
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter(tags=["category-documents"])


# Allowed types for Phase 1D. Parsing is Phase 2; we accept the broader set
# now so the UI doesn't reject what the parser will eventually support.
_ALLOWED_MIME_PREFIXES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/msword",  # legacy .doc
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.ms-excel",  # legacy .xls
    "text/",  # txt, markdown, csv
)
_MAX_BYTES = 50 * 1024 * 1024  # 50 MB hard cap


def _to_schema(doc: CategoryDocument, with_url: bool = False) -> CategoryDocumentSchema:
    payload = CategoryDocumentSchema.model_validate(doc)
    if with_url and storage.is_configured:
        try:
            payload.download_url = storage.presigned_get_url(doc.storage_key, expires_in=3600)
        except Exception as exc:
            logger.warning("Could not generate download URL for %s: %s", doc.id, exc)
    return payload


def _enqueue_processing(document_id: str, background_tasks: BackgroundTasks) -> None:
    """Async-first dispatch — Celery when configured, BackgroundTasks fallback."""
    if settings.USE_CELERY:
        from app.celery_tasks.document_tasks import process_document
        process_document.delay(document_id)
        return

    # Local dev path without a broker.
    from app.celery_tasks.document_tasks import process_document as _proc

    def _run():
        _proc(document_id)  # call the underlying function via .run()? No — the
        # decorated task is callable directly when not using a broker.

    # Calling a Celery-decorated task directly executes its body synchronously,
    # which is what we want in the no-broker dev path.
    background_tasks.add_task(lambda: _proc(document_id))


@router.post(
    "/categories/{category_id}/documents",
    response_model=CategoryDocumentSchema,
    status_code=201,
)
def upload_category_document(
    category_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    category = document_service.category_in_user_org(db, user, category_id)

    if not storage.is_configured:
        raise HTTPException(
            status_code=503,
            detail="Document storage is not configured on this server.",
        )

    # MIME guard — accept-list, not block-list.
    mime = (file.content_type or "").lower()
    if not any(mime.startswith(p) for p in _ALLOWED_MIME_PREFIXES):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {mime or 'unknown'}",
        )

    # Build a deterministic storage key. Per-category prefix keeps Phase 2's
    # bulk re-ingest queries cheap. Trailing UUID guarantees uniqueness even
    # for re-uploads of the same filename.
    suffix = os.path.splitext(file.filename or "")[1].lower()
    storage_key = f"org/{user.organization_id}/category/{category_id}/{uuid.uuid4()}{suffix}"

    # Stream upload + size check. SpooledTemporaryFile under the hood means
    # FastAPI already buffers to disk for large files.
    file.file.seek(0, os.SEEK_END)
    size_bytes = file.file.tell()
    file.file.seek(0)

    if size_bytes > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {size_bytes} bytes (limit {_MAX_BYTES}).",
        )
    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail="Empty file.")

    try:
        storage.upload_fileobj(file.file, storage_key, content_type=file.content_type)
    except Exception as exc:
        logger.error("Storage upload failed: %s", exc)
        raise HTTPException(status_code=502, detail="Storage upload failed.") from exc

    doc = document_service.create_document(
        db,
        user,
        category,
        name=file.filename or "untitled",
        original_filename=file.filename or "untitled",
        mime_type=file.content_type,
        size_bytes=size_bytes,
        storage_key=storage_key,
    )

    # Async-first: kick off processing without blocking the response.
    _enqueue_processing(str(doc.id), background_tasks)

    return _to_schema(doc, with_url=True)


@router.get(
    "/categories/{category_id}/documents",
    response_model=List[CategoryDocumentSchema],
)
def list_category_documents(
    category_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    docs = document_service.list_documents(db, user, category_id)
    return [_to_schema(d, with_url=True) for d in docs]


@router.get(
    "/categories/{category_id}/documents/{document_id}",
    response_model=CategoryDocumentSchema,
)
def get_category_document(
    category_id: int,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = document_service.get_owned_document(db, user, category_id, document_id)
    return _to_schema(doc, with_url=True)


@router.delete("/categories/{category_id}/documents/{document_id}")
def delete_category_document(
    category_id: int,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = document_service.get_owned_document(db, user, category_id, document_id)

    # Best-effort storage cleanup. If the object is already gone, the row
    # is still removed — orphan storage objects are reclaimable later.
    try:
        if storage.is_configured:
            storage.delete(doc.storage_key)
    except Exception as exc:
        logger.warning("Storage delete failed for %s: %s", doc.storage_key, exc)

    document_service.delete_document(db, doc)
    return {"status": "ok", "deleted_id": str(document_id)}


# ---------------------------------------------------------------------------
# Manual retry. Mirrors the meeting retry endpoints in app/api/routes.py —
# the AI Memory pipeline normally fans out on upload, but a transient
# OpenAI / parser failure needs a one-click re-run from the UI.
# ---------------------------------------------------------------------------


@router.post("/categories/{category_id}/documents/{document_id}/retry-embedding")
def retry_category_document_embedding(
    category_id: int,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    document_service.mark_document_embedding_pending(db, user, category_id, document_id)
    from app.celery_tasks.document_ingest import dispatch_ingest_document
    dispatch_ingest_document("category", str(document_id))
    return {"status": "dispatched", "document_id": str(document_id), "stage": "embedding"}


@router.post("/categories/{category_id}/documents/{document_id}/retry-graph")
def retry_category_document_graph(
    category_id: int,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    document_service.mark_document_graph_pending(db, user, category_id, document_id)
    try:
        from app.celery_tasks.document_graph_tasks import (
            dispatch_extract_document_graph,
        )
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Document graph extraction is not enabled yet (Phase 4D pending).",
        )
    dispatch_extract_document_graph("category", str(document_id))
    return {"status": "dispatched", "document_id": str(document_id), "stage": "graph"}
