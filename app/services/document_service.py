"""Database logic for category-scoped documents (Phase 1D).

Extracted from ``app/api/document_router.py`` so the router stays a thin
transport layer. Functions take the SQLAlchemy ``Session`` plus the current
user and raise ``HTTPException`` for ownership / integrity failures — this
mirrors ``category_service`` and keeps behaviour identical to the previous
in-router helpers.

Note: this is a *different* concern from ``document_chunker.py`` (Phase 2
chunking); this module owns persistence for the ``CategoryDocument`` rows.
"""

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Category, CategoryDocument


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------


def category_in_user_org(db: Session, user, category_id: int) -> Category:
    category = (
        db.query(Category)
        .filter(
            Category.id == category_id,
            Category.organization_id == user.organization_id,
        )
        .first()
    )
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


def get_owned_document(
    db: Session, user, category_id: int, document_id
) -> CategoryDocument:
    """Resolve a document within a category the caller's org owns (404 on miss)."""
    category_in_user_org(db, user, category_id)
    doc = (
        db.query(CategoryDocument)
        .filter(
            CategoryDocument.id == document_id,
            CategoryDocument.category_id == category_id,
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
    category: Category,
    *,
    name: str,
    original_filename: str,
    mime_type,
    size_bytes: int,
    storage_key: str,
) -> CategoryDocument:
    doc = CategoryDocument(
        organization_id=user.organization_id,
        category_id=category.id,
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
        # Storage_key is UUID-suffixed, so this should never happen in practice;
        # if it does, surface a clean error rather than a 500.
        raise HTTPException(status_code=409, detail="Storage key collision; retry the upload.")
    db.refresh(doc)
    return doc


def list_documents(db: Session, user, category_id: int):
    category_in_user_org(db, user, category_id)
    return (
        db.query(CategoryDocument)
        .filter(CategoryDocument.category_id == category_id)
        .order_by(CategoryDocument.created_at.desc())
        .all()
    )


def delete_document(db: Session, doc: CategoryDocument) -> None:
    db.delete(doc)
    db.commit()


# ---------------------------------------------------------------------------
# Retry state transitions
# ---------------------------------------------------------------------------


def mark_document_embedding_pending(
    db: Session, user, category_id: int, document_id
) -> CategoryDocument:
    doc = get_owned_document(db, user, category_id, document_id)
    doc.embedding_status = "pending"
    doc.error_message = None
    db.commit()
    return doc


def mark_document_graph_pending(
    db: Session, user, category_id: int, document_id
) -> CategoryDocument:
    doc = get_owned_document(db, user, category_id, document_id)
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
