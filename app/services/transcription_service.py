"""Database logic for transcript retrieval.

Extracted from ``app/api/transcription_router.py`` so the router stays a thin
transport layer. Functions take the SQLAlchemy ``Session`` plus the current
user and raise ``HTTPException`` for ownership failures — mirroring the
convention used by ``category_service``.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import Meeting


def get_owned_meeting(db: Session, user, meeting_id: int) -> Meeting:
    """Load a meeting owned by ``user`` or raise 404 (which also covers the
    access-denied case — we do not distinguish missing vs. not-owned)."""
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found or access denied")
    return meeting
