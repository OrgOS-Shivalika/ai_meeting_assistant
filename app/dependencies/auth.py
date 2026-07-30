from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from app.db.database import get_db
from sqlalchemy.orm import Session
from app.db.models import User
from app.config.settings import settings
from app.utils.admin_enums import PromptRole
import uuid

SECRET_KEY = settings.AUTH_SECRET_KEY
ALGORITHM = settings.ALGORITHM

# auto_error=False: the JWT now lives in an HttpOnly cookie, so a missing
# Authorization header is normal — we fall back to the cookie below rather
# than letting the scheme raise a 401 first. Kept in the graph so Swagger's
# "Authorize" box and non-browser API clients can still send a Bearer token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def _token_from_request(request: Request, bearer_token: str | None) -> str | None:
    """Resolve the JWT for an HTTP request.

    Cookie first (the browser SPA's HttpOnly `access_token`), then the
    Authorization Bearer header (Swagger + programmatic API clients). The
    cookie wins when both are present so a browser session isn't shadowed
    by a stale header.
    """
    cookie_token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    return cookie_token or bearer_token


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


# Endpoints reachable while `must_change_password` is set. Matched as a
# suffix so the API/public prefix doesn't have to be hardcoded here.
#
# The set is deliberately tiny: enough to sign in, see who you are, set
# a password and sign out. An admin provisioned with a generated
# password has, by definition, a credential that was transmitted out of
# band — the window where it works should cover exactly the act of
# replacing it and nothing else.
_PASSWORD_CHANGE_ALLOWED_SUFFIXES = (
    "/auth/me",
    "/auth/change-password",
    "/auth/logout",
    "/auth/login",
)


def get_current_user(
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = _token_from_request(request, bearer_token)
    user = resolve_user_from_token(db, token)
    if user is None:
        raise credentials_exception

    # Forced password change. Enforced here rather than as a per-route
    # dependency so a route added tomorrow inherits it — the failure mode
    # of the alternative is a forgotten guard on exactly the endpoint
    # that mattered.
    if getattr(user, "must_change_password", False):
        path = request.url.path.rstrip("/")
        if not any(path.endswith(s) for s in _PASSWORD_CHANGE_ALLOWED_SUFFIXES):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must set a new password before using the application.",
            )
    return user


# ---------------------------------------------------------------------------
# Phase 7E — RBAC
#
# `User.role` is one of VIEWER | PROMPT_EDITOR | ORG_ADMIN, stored
# UPPERCASE. Canonical definition: `app/utils/admin_enums.PromptRole`,
# which also owns the privilege ordering.
#
# NULL is treated as VIEWER (safe-deny default). The 7E migration
# backfills existing rows to ORG_ADMIN so no user loses access.
# The dependency helpers below are designed to be drop-in `Depends()`
# slots — the route declares `user: User = Depends(require_org_admin)`
# and gets a 403 if the user's role isn't sufficient.
#
# NOTE: this is NOT the meeting-access role. `users.access_role`
# (`AccessRole`) governs meetings, tasks and boards and is a separate
# column with a separate meaning for its identically-named ORG_ADMIN.
# ---------------------------------------------------------------------------


def _user_rank(user: User) -> int:
    """Resolve the user's effective rank. NULL / unknown role → VIEWER."""
    return PromptRole.coerce(getattr(user, "role", None)).rank


def require_prompt_editor(
    user: User = Depends(get_current_user),
) -> User:
    """Allow PROMPT_EDITOR + ORG_ADMIN. Used on draft/publish/rollback
    endpoints."""
    if _user_rank(user) < PromptRole.PROMPT_EDITOR.rank:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires role '{PromptRole.PROMPT_EDITOR}' or higher.",
        )
    return user


def require_org_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Allow ORG_ADMIN only. Used on archive + playground + eval-gate
    config endpoints."""
    if _user_rank(user) < PromptRole.ORG_ADMIN.rank:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires role '{PromptRole.ORG_ADMIN}'.",
        )
    return user