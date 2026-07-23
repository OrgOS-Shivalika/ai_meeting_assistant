"""Database logic for the Google OAuth connect / disconnect flows.

Extracted from ``app/api/google_auth_router.py`` so the router stays a thin
transport layer. The OAuth redirect derivation and the actual HTTP token /
profile exchange with Google stay in the router (that's transport wiring);
what lives here is the persistence of the resulting credentials onto the
``User`` row. Functions take the SQLAlchemy ``Session`` and raise
``HTTPException`` for failures, mirroring the existing service convention.
"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import User
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def persist_google_tokens(db: Session, user, *, access_token, refresh_token, expires_in, profile) -> None:
    """Persist freshly-exchanged Google credentials onto the user row.

    ``expires_in`` is the seconds-to-live Google returns; we translate it to
    an absolute UTC timestamp for storage. A missing ``refresh_token`` keeps
    the existing one (Google only returns it on first consent)."""
    expires_at = None
    if expires_in:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Manual update to ensure persistence
    db.query(User).filter(User.id == user.id).update({
        "google_access_token": access_token,
        "google_refresh_token": refresh_token if refresh_token else User.google_refresh_token,
        "google_token_expires_at": expires_at,
        "google_profile_name": profile.get("name"),
        "google_profile_picture": profile.get("picture")
    })

    db.commit()

    # Verify immediately
    db.refresh(user)


def disconnect_google(db: Session, user) -> dict:
    try:
        db.query(User).filter(User.id == user.id).update({
            "google_access_token": None,
            "google_refresh_token": None,
            "google_token_expires_at": None,
            "google_profile_name": None,
            "google_profile_picture": None
        })
        db.commit()
        return {"message": "Google Calendar disconnected successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error disconnecting Google for user {user.email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to disconnect Google Calendar")
