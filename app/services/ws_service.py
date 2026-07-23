"""Database logic for the WebSocket routes.

Extracted from ``app/api/ws_router.py`` so the router keeps only the
transport / handshake wiring. Only the plain meeting lookup is moved here;
the websocket lifecycle (accept/close, session creation/teardown) stays in
the router. Functions take the SQLAlchemy ``Session`` as the first arg,
matching the ``category_service`` convention.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import Meeting


def get_meeting_by_id(db: Session, meeting_id: int) -> Optional[Meeting]:
    """Fetch a meeting row by id, or None. Org-scope enforcement stays in
    the caller so the websocket handshake can close with the right code."""
    return db.query(Meeting).filter(Meeting.id == meeting_id).first()
