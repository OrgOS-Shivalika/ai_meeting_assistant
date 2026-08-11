"""Database logic for the closing-briefing endpoints.

Extracted from ``app/api/closing_briefing_router.py`` so the router stays a
thin transport layer. Functions take the SQLAlchemy ``Session`` plus the
current user and raise ``HTTPException`` for tenancy failures — this mirrors
the existing convention (see ``category_service``) and keeps behaviour
identical to the previous in-router helpers.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services import permissions
from app.db.models import ClosingBriefing, Meeting


def load_briefing_for_user(
    db: Session, current_user, meeting_id: int
) -> ClosingBriefing:
    """Access-scoped load. 404 on a missing row or cross-org access; 403
    when the meeting is in the caller's org but outside their scope."""
    verify_meeting_tenancy(db, current_user, meeting_id)
    row = (
        db.query(ClosingBriefing)
        .filter(ClosingBriefing.meeting_id == meeting_id)
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404, detail="Closing briefing not found for this meeting."
        )
    return row


def verify_meeting_tenancy(db: Session, current_user, meeting_id: int) -> Meeting:
    """Access gate for every closing-briefing endpoint. Confirms the
    meeting exists, belongs to the caller's org, AND is within their
    access scope. Returns the Meeting row so callers can use bot_id,
    closing_briefing_status, etc.

    Name kept for its six call sites; it now checks more than tenancy.
    Worth the check being here rather than in the router: the briefing
    is a spoken summary of the meeting, and the audio endpoint mints a
    presigned URL to a recording of it.
    """
    return permissions.get_viewable_meeting(db, current_user, meeting_id)


def get_briefing_row(db: Session, meeting_id: int) -> Optional[ClosingBriefing]:
    """Fetch the closing-briefing audit row for a meeting, or None. Used by
    the sync speak-now path to re-read the row after the executor finishes."""
    return (
        db.query(ClosingBriefing)
        .filter(ClosingBriefing.meeting_id == meeting_id)
        .first()
    )
