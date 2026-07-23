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

from app.db.models import ClosingBriefing, Meeting


def load_briefing_for_user(
    db: Session, current_user, meeting_id: int
) -> ClosingBriefing:
    """Tenant-scoped load. 404 on missing row OR cross-org access — the
    convention used elsewhere is "indistinguishable 404" rather than 403."""
    row = (
        db.query(ClosingBriefing)
        .join(Meeting, Meeting.id == ClosingBriefing.meeting_id)
        .filter(ClosingBriefing.meeting_id == meeting_id)
        .filter(Meeting.organization_id == current_user.organization_id)
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404, detail="Closing briefing not found for this meeting."
        )
    return row


def verify_meeting_tenancy(db: Session, current_user, meeting_id: int) -> Meeting:
    """Tenant gate: confirms the meeting exists AND belongs to the
    caller's org. Returns the Meeting row so callers can use bot_id,
    closing_briefing_status, etc."""
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id)
        .filter(Meeting.organization_id == current_user.organization_id)
        .first()
    )
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting


def get_briefing_row(db: Session, meeting_id: int) -> Optional[ClosingBriefing]:
    """Fetch the closing-briefing audit row for a meeting, or None. Used by
    the sync speak-now path to re-read the row after the executor finishes."""
    return (
        db.query(ClosingBriefing)
        .filter(ClosingBriefing.meeting_id == meeting_id)
        .first()
    )
