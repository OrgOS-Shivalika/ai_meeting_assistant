from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from app.db.database import get_db
from sqlalchemy.orm import Session
from app.db.models import User
from app.config.settings import settings
from app.utils.admin_enums import PromptRole
from datetime import datetime, timezone
import uuid

from app.services import auth_service
from app.utils.auth_cookie import set_auth_cookie

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


def token_claims(token: str | None) -> dict:
    """Decoded claims, or `{}` on any failure.

    For reading a NON-identity claim (currently `remember`) off the caller's
    live cookie. Never use this to establish who someone is — that path must
    go through `resolve_user_from_token`, which also enforces the
    password-change revocation check this deliberately skips.
    """
    if not token:
        return {}
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return {}


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
        user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
        if user is None:
            return None
        if _issued_before_password_change(user, payload.get("iat")):
            return None
        return user
    except (JWTError, ValueError):
        # ValueError catches malformed UUIDs.
        return None


# The JWT is stateless with a 7-day TTL, so there is nothing to delete
# server-side when a password changes. `users.password_set_at` is the
# revocation point instead: a token issued before the hash last changed is
# refused. That is what makes an admin password reset actually cut off a
# live session rather than merely changing what the next login needs.
#
# `iat` is whole seconds while `password_set_at` carries microseconds, so a
# token minted in the same instant as the change would compare as older
# than it. The leeway keeps a fresh login — and registration, which sets
# the timestamp then immediately issues a token — from invalidating itself.
_TOKEN_CLOCK_LEEWAY_SECONDS = 30


def _issued_before_password_change(user: User, issued_at) -> bool:
    """True when this token predates the user's current password.

    Fails OPEN for tokens with no `iat` claim: those were minted before
    this check existed, and refusing them would sign out every active
    session on deploy. They expire within the 7-day TTL anyway.
    """
    changed_at = getattr(user, "password_set_at", None)
    if changed_at is None or issued_at is None:
        return False
    if changed_at.tzinfo is None:
        # Postgres returns aware datetimes; a naive one means a fixture or
        # a backend without timezone support. Assume UTC rather than the
        # server's local zone, which would shift the comparison by hours.
        changed_at = changed_at.replace(tzinfo=timezone.utc)
    return changed_at.timestamp() > float(issued_at) + _TOKEN_CLOCK_LEEWAY_SECONDS


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


# Re-issue the cookie once a session is this far through its life. At the
# 7-day TTL that is 3.5 days, so anyone who opens the app at least twice a
# week never sees a login screen — which is what "keep me signed in" is
# actually asking for.
#
# Without this the TTL is a HARD WALL: the token and the cookie are both
# minted at login and nothing ever renews them, so a daily user was logged
# out every 7 days no matter how much they used the product.
_REFRESH_AFTER_FRACTION = 0.5

# Never refresh on the way out — logout appends a `delete_cookie` to the same
# response, and whichever Set-Cookie lands last wins. A refresh here would
# hand the browser a fresh session on the very request meant to end it.
_NO_REFRESH_SUFFIXES = ("/auth/logout", "/auth/login", "/auth/change-password")


def _maybe_refresh_session(
    request: Request, response: Response, user: User, token: str
) -> None:
    """Slide the session forward when it is past half its life.

    Deliberately narrow about when it fires:

    * COOKIE sessions only. A Bearer-token client (Swagger, a script) has no
      cookie to refresh and should not suddenly be handed one.
    * Not on login/logout/change-password, each of which writes its own
      cookie on the same response.
    * Tokens with no `iat`/`exp` are left alone — those predate this and will
      age out on their own.

    The `remember` claim is carried across, so a session cookie stays a
    session cookie. Refreshing it into a persistent one would quietly undo
    the choice made at login.
    """
    if request.cookies.get(settings.AUTH_COOKIE_NAME) != token:
        return
    path = request.url.path.rstrip("/")
    if any(path.endswith(s) for s in _NO_REFRESH_SUFFIXES):
        return

    claims = token_claims(token)
    exp, iat = claims.get("exp"), claims.get("iat")
    if exp is None or iat is None:
        return
    lifetime = float(exp) - float(iat)
    if lifetime <= 0:
        return
    elapsed = datetime.now(timezone.utc).timestamp() - float(iat)
    if elapsed < lifetime * _REFRESH_AFTER_FRACTION:
        return

    remember = bool(claims.get("remember", True))
    set_auth_cookie(
        response,
        auth_service.create_token({"user_id": str(user.id), "remember": remember}),
        remember=remember,
    )


def get_current_user(
    request: Request,
    response: Response,
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

    # Slide the expiry forward for an active session. Runs after the token
    # has been fully validated above, so this can only ever extend a session
    # that was already good — it cannot resurrect a revoked or expired one.
    _maybe_refresh_session(request, response, user, token)

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