from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from app.db.database import get_db
from sqlalchemy.orm import Session
from app.db.models import User
from app.config.settings import settings
import uuid

SECRET_KEY = settings.AUTH_SECRET_KEY
ALGORITHM = settings.ALGORITHM

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def resolve_user_from_token(db: Session, token: str | None) -> User | None:
    """Decode a JWT string → User, or None on any failure.

    Reusable outside the HTTP OAuth2 dependency — WebSockets don't hit
    `oauth2_scheme` because browsers can't send custom headers on the
    WS handshake. Callers (WS handlers) do their own close-code
    handling; this function stays exception-free for that reason.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("user_id")
        if user_id is None:
            return None
        return db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    except (JWTError, ValueError):
        # ValueError catches malformed UUIDs.
        return None


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = resolve_user_from_token(db, token)
    if user is None:
        raise credentials_exception
    return user


# ---------------------------------------------------------------------------
# Phase 7E — RBAC
#
# `User.role` is one of:
#   - 'viewer'        — read-only on agent surfaces
#   - 'prompt_editor' — viewer + create/edit drafts, publish, rollback
#   - 'org_admin'     — prompt_editor + archive profiles, run playground,
#                       view audit log
#
# NULL is treated as 'viewer' (safe-deny default). The 7E migration
# backfills existing rows to 'org_admin' so no user loses access.
# The dependency helpers below are designed to be drop-in `Depends()`
# slots — the route declares `user: User = Depends(require_org_admin)`
# and gets a 403 if the user's role isn't sufficient.
# ---------------------------------------------------------------------------

_ROLE_RANK = {
    "viewer": 0,
    "prompt_editor": 1,
    "org_admin": 2,
}


def _user_rank(user: User) -> int:
    """Resolve the user's effective rank. NULL role → viewer."""
    return _ROLE_RANK.get(user.role or "viewer", 0)


def require_prompt_editor(
    user: User = Depends(get_current_user),
) -> User:
    """Allow prompt_editor + org_admin. Used on draft/publish/rollback
    endpoints."""
    if _user_rank(user) < _ROLE_RANK["prompt_editor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires role 'prompt_editor' or higher.",
        )
    return user


def require_org_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Allow org_admin only. Used on archive + playground + eval-gate
    config endpoints."""
    if _user_rank(user) < _ROLE_RANK["org_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires role 'org_admin'.",
        )
    return user