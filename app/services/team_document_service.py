"""Database logic for team-scoped documents.

Extracted from ``app/api/team_document_router.py`` so the router stays a thin
transport layer. Mirrors ``document_service`` exactly but scoped one level
deeper to a specific team within a category. Functions take the SQLAlchemy
``Session`` plus the current user and raise ``HTTPException`` for ownership /
integrity failures, matching the ``category_service`` convention.
"""

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Category, Team, TeamDocument


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------


def team_in_user_org(db: Session, user, team_id: int) -> Team:
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


def get_owned_document(
    db: Session, user, team_id: int, document_id
) -> TeamDocument:
    """Resolve a document within a team the caller's org owns (404 on miss)."""
    team_in_user_org(db, user, team_id)
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
    return doc


# ---------------------------------------------------------------------------
# Document persistence
# ---------------------------------------------------------------------------


def create_document(
    db: Session,
    user,
    team: Team,
    *,
    name: str,
    original_filename: str,
    mime_type,
    size_bytes: int,
    storage_key: str,
) -> TeamDocument:
    doc = TeamDocument(
        organization_id=user.organization_id,
        team_id=team.id,
        uploaded_by_user_id=user.id,
        name=name,
        original_filename=original_filename,
        mime_type=mime_type,
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
    return doc


def list_documents(db: Session, user, team_id: int):
    team_in_user_org(db, user, team_id)
    return (
        db.query(TeamDocument)
        .filter(TeamDocument.team_id == team_id)
        .order_by(TeamDocument.created_at.desc())
        .all()
    )


def delete_document(db: Session, doc: TeamDocument) -> None:
    db.delete(doc)
    db.commit()


# ---------------------------------------------------------------------------
# Retry state transitions
# ---------------------------------------------------------------------------


def mark_document_embedding_pending(
    db: Session, user, team_id: int, document_id
) -> TeamDocument:
    doc = get_owned_document(db, user, team_id, document_id)
    doc.embedding_status = "pending"
    doc.error_message = None
    db.commit()
    return doc


def mark_document_graph_pending(
    db: Session, user, team_id: int, document_id
) -> TeamDocument:
    doc = get_owned_document(db, user, team_id, document_id)
    if doc.embedding_status != "embedded":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Document embeddings aren't ready (embedding_status="
                f"{doc.embedding_status}); cannot retry graph extraction yet."
            ),
        )
    doc.graph_status = "pending"
    db.commit()
    return doc
