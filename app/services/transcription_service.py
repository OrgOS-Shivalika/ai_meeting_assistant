"""Database logic for transcript retrieval.

Extracted from ``app/api/transcription_router.py`` so the router stays a thin
transport layer. Functions take the SQLAlchemy ``Session`` plus the current
user and raise ``HTTPException`` for ownership failures — mirroring the
convention used by ``category_service``.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import Meeting
from app.services import permissions


def get_owned_meeting(db: Session, user, meeting_id: int) -> Meeting:
    """Load a meeting the caller may read, or raise.

    Was `Meeting.user_id == user.id` — creator-only, which is both
    narrower than the access rules (an attendee couldn't read the
    transcript of their own meeting) and unrelated to them (the creator
    keeps access after being removed from a category). Now it routes
    through the same scope everything else uses: 404 cross-org, 403
    in-org but out of scope.
    """
    return permissions.get_viewable_meeting(db, user, meeting_id)
