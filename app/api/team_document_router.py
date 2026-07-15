"""Team-document upload routes.

Mirrors `app/api/document_router.py` exactly — same async-first contract,
same MIME accept-list, same size cap, same storage key pattern — but scoped
one level deeper to a specific team within a category.
"""

from __future__ import annotations

import os
import uuid
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.config.settings import settings
from app.db.models import Category, Team, TeamDocument
from app.dependencies.auth import get_current_user
from app.schemas.document_schema import TeamDocumentSchema
from app.services.storage_service import storage
from app.utils.enums import EmbeddingStatus, GraphStatus
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter(tags=["team-documents"])


_ALLOWED_MIME_PREFIXES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/",
)
_MAX_BYTES = 50 * 1024 * 1024


def _team_in_user_org(db: Session, user, team_id: int) -> Team:
    """Resolve a team and check it belongs to the caller's org via its parent
    category. Returns 404 (not 403) on a cross-org access to avoid leaking
    existence."""
    team = (
        db.query(Team)
        .join(Category, Team.category_id == Category.id)
        .filter(
            Team.id == team_id,
            Category.organization_id == user.organization_id,
        )
        .first()
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _to_schema(doc: TeamDocument, with_url: bool = False) -> TeamDocumentSchema:
    payload = TeamDocumentSchema.model_validate(doc)
    if with_url and storage.is_configured:
        try:
            payload.download_url = storage.presigned_get_url(doc.storage_key, expires_in=3600)
        except Exception as exc:
            logger.warning("Could not generate download URL for %s: %s", doc.id, exc)
    return payload


def _enqueue_processing(document_id: str, background_tasks: BackgroundTasks) -> None:
    if settings.USE_CELERY:
        from app.celery_tasks.team_document_tasks import process_team_document
        process_team_document.delay(document_id)
        return

    from app.celery_tasks.team_document_tasks import process_team_document as _proc
    background_tasks.add_task(lambda: _proc(document_id))


@router.post(
    "/teams/{team_id}/documents",
    response_model=TeamDocumentSchema,
    status_code=201,
)
def upload_team_document(
    team_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    team = _team_in_user_org(db, user, team_id)

    if not storage.is_configured:
        raise HTTPException(
            status_code=503,
            detail="Document storage is not configured on this server.",
        )

    mime = (file.content_type or "").lower()
    if not any(mime.startswith(p) for p in _ALLOWED_MIME_PREFIXES):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {mime or 'unknown'}",
        )

    suffix = os.path.splitext(file.filename or "")[1].lower()
    storage_key = f"org/{user.organization_id}/team/{team_id}/{uuid.uuid4()}{suffix}"

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

    doc = TeamDocument(
        organization_id=user.organization_id,
        team_id=team.id,
        uploaded_by_user_id=user.id,
        name=file.filename or "untitled",
        original_filename=file.filename or "untitled",
        mime_type=file.content_type,
        size_bytes=size_bytes,
        storage_key=storage_key,
        status="uploaded",
    )
    db.add(doc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Storage key collision; retry the upload.")
    db.refresh(doc)

    _enqueue_processing(str(doc.id), background_tasks)

    return _to_schema(doc, with_url=True)


@router.get(
    "/teams/{team_id}/documents",
    response_model=List[TeamDocumentSchema],
)
def list_team_documents(
    team_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _team_in_user_org(db, user, team_id)
    docs = (
        db.query(TeamDocument)
        .filter(TeamDocument.team_id == team_id)
        .order_by(TeamDocument.created_at.desc())
        .all()
    )
    return [_to_schema(d, with_url=True) for d in docs]


@router.get(
    "/teams/{team_id}/documents/{document_id}",
    response_model=TeamDocumentSchema,
)
def get_team_document(
    team_id: int,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _team_in_user_org(db, user, team_id)
    doc = (
        db.query(TeamDocument)
        .filter(
            TeamDocument.id == document_id,
            TeamDocument.team_id == team_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_schema(doc, with_url=True)


@router.delete("/teams/{team_id}/documents/{document_id}")
def delete_team_document(
    team_id: int,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _team_in_user_org(db, user, team_id)
    doc = (
        db.query(TeamDocument)
        .filter(
            TeamDocument.id == document_id,
            TeamDocument.team_id == team_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        if storage.is_configured:
            storage.delete(doc.storage_key)
    except Exception as exc:
        logger.warning("Storage delete failed for %s: %s", doc.storage_key, exc)

    db.delete(doc)
    db.commit()
    return {"status": "ok", "deleted_id": str(document_id)}


# ---------------------------------------------------------------------------
# Manual retry (mirrors document_router.py).
# ---------------------------------------------------------------------------


@router.post("/teams/{team_id}/documents/{document_id}/retry-embedding")
def retry_team_document_embedding(
    team_id: int,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _team_in_user_org(db, user, team_id)
    doc = (
        db.query(TeamDocument)
        .filter(
            TeamDocument.id == document_id,
            TeamDocument.team_id == team_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.embedding_status = EmbeddingStatus.PENDING
    doc.error_message = None
    db.commit()
    from app.celery_tasks.document_ingest import dispatch_ingest_document
    dispatch_ingest_document("team", str(document_id))
    return {"status": "dispatched", "document_id": str(document_id), "stage": "embedding"}


@router.post("/teams/{team_id}/documents/{document_id}/retry-graph")
def retry_team_document_graph(
    team_id: int,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _team_in_user_org(db, user, team_id)
    doc = (
        db.query(TeamDocument)
        .filter(
            TeamDocument.id == document_id,
            TeamDocument.team_id == team_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.embedding_status != EmbeddingStatus.EMBEDDED:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Document embeddings aren't ready (embedding_status="
                f"{doc.embedding_status}); cannot retry graph extraction yet."
            ),
        )
    doc.graph_status = GraphStatus.PENDING
    db.commit()
    try:
        from app.celery_tasks.document_graph_tasks import (
            dispatch_extract_document_graph,
        )
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Document graph extraction is not enabled yet (Phase 4D pending).",
        )
    dispatch_extract_document_graph("team", str(document_id))
    return {"status": "dispatched", "document_id": str(document_id), "stage": "graph"}
