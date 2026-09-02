from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import User
from app.dependencies.auth import get_current_user, token_claims
from app.services import admin_service, auth_service, permissions
from app.schemas.admin_schema import PasswordChangeRequest
from app.schemas.auth_schema import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    Token,
    UserCreate,
    UserLogin,
)
from app.services import password_reset_service
from app.config.settings import settings
from app.utils.auth_cookie import set_auth_cookie
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Two routers, same `/auth` sub-path, mounted under different top-level
# prefixes in main.py:
#   public_router → PUBLIC_PREFIX  (register + login — no JWT required)
#   router        → API_PREFIX     (me + logout — authenticated session)
public_router = APIRouter(prefix="/auth", tags=["Authentication"])
router = APIRouter(prefix="/auth", tags=["Authentication"])


# Moved to `utils/auth_cookie` so `dependencies/auth` can set the same cookie
# for the sliding refresh without importing this router.
_set_auth_cookie = set_auth_cookie


@public_router.post("/register")
def register(data: UserCreate, db: Session = Depends(get_db)):
    return auth_service.register_user(db, data)

@public_router.post("/login", response_model=Token)
def login(data: UserLogin, response: Response, db: Session = Depends(get_db)):
    user = auth_service.authenticate_user(db, data)
    # The choice rides in the token so it survives a re-issue — see
    # `change_password`, which would otherwise silently upgrade a
    # deliberately non-persistent session to a 7-day one.
    token = auth_service.create_token(
        {"user_id": str(user.id), "remember": data.remember_me}
    )
    _set_auth_cookie(response, token, remember=data.remember_me)
    # The body token is retained for non-browser API clients (Swagger,
    # scripts) that authenticate via the Authorization header. Browser
    # sessions rely solely on the HttpOnly cookie set above and never
    # persist this value.
    return {"access_token": token, "token_type": "bearer"}


@router.post("/logout")
def logout(response: Response):
    """Clear the session cookie. JS can't delete an HttpOnly cookie, so the
    SPA calls this on sign-out; the delete must echo the same path/samesite/
    secure attributes the cookie was set with for browsers to drop it."""
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    return {"message": "Logged out"}


@router.get("/me")
def get_me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the authenticated user, their organization and their access
    role.

    The role fields are what the SPA renders against — which dashboard to
    show, whether to draw a "New meeting" button. They are a UI hint
    only: every endpoint re-derives the same answer server-side, because
    a hidden button is not an access control.
    """
    org = user.organization
    role = permissions.access_role(user)
    managed = permissions.managed_category_ids(db, user)
    managed_teams = permissions.managed_team_ids(db, user)
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "google_profile_picture": user.google_profile_picture,
        # Meeting access control. Distinct from `role` (Phase 7E), which
        # governs the agent-prompt surfaces and is exposed separately.
        "access_role": role,
        # None means "all categories" (org admin). An empty list means
        # this user administers none — the two are not the same and the
        # frontend must not conflate them.
        #
        # WHOLE-category grants only. A grant scoped to one team appears
        # in `managed_team_ids` instead; reporting it here would make a
        # team-level grant look like control of the entire category, and
        # the UI would draw manage controls the server then refuses.
        #
        # A scope is not a role: a MEMBER can hold these, in which case
        # they mean read access, not management. Pair them with
        # `access_role` before enabling anything destructive.
        "managed_category_ids": managed,
        "managed_team_ids": managed_teams,
        "must_change_password": bool(user.must_change_password),
        "prompt_role": user.role,
        "organization": {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
        } if org else None,
    }


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Set a new password.

    Also the exit from `must_change_password`, which is how an admin
    provisioned with a generated password takes ownership of their
    account.

    Issues a fresh cookie on the way out. Changing the password moves
    `password_set_at`, which revokes every token minted before it — the
    point being to end sessions elsewhere, but that includes the one
    making this request. Re-issuing here means the caller stays signed in
    and everyone else holding an older cookie does not.
    """
    result = admin_service.change_password(
        db, user, payload.current_password, payload.new_password
    )
    # Carry the caller's original "keep me signed in" answer across the
    # re-issue. Defaulting to persistent here would hand a 7-day cookie to
    # someone who explicitly asked not to have one, just because they changed
    # their password.
    remember = bool(
        token_claims(request.cookies.get(settings.AUTH_COOKIE_NAME)).get("remember", True)
    )
    _set_auth_cookie(
        response,
        auth_service.create_token({"user_id": str(user.id), "remember": remember}),
        remember=remember,
    )
    return result


# ---------------------------------------------------------------------------
# Self-service password reset
# ---------------------------------------------------------------------------
#
# Both endpoints are PUBLIC by necessity — someone who cannot sign in cannot
# authenticate to ask for help. That makes them the most exposed surface in
# the app, so the rules they follow are in
# `services/password_reset_service`, which is where the reasoning lives.

# The one response the request endpoint ever gives. A single constant rather
# than two call sites, because the whole defence is that these are
# indistinguishable and two strings drift apart.
_RESET_REQUESTED_MESSAGE = (
    "If an account exists for that email, a reset link is on its way."
)


@public_router.post("/forgot-password", status_code=202)
def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start a password reset. Always 202, always the same body.

    The work runs as a BACKGROUND task, and that is a security property, not
    a performance one: sending mail takes an SMTP round-trip, so doing it
    inline would make a request for a REAL address measurably slower than one
    for an address that does not exist. Identical text plus a timing side
    channel is still an enumeration oracle.
    """
    client_ip = request.client.host if request.client else None
    background.add_task(
        _run_reset_request, data.email, client_ip
    )
    return {"message": _RESET_REQUESTED_MESSAGE}


def _run_reset_request(email: str, client_ip: str | None) -> None:
    """Background half of `forgot_password`.

    Opens its OWN session: the request-scoped one from `get_db` is closed
    the moment the response goes out, and this runs after that.

    Swallows everything. A background task has no caller to report to, and an
    exception escaping here would only appear in the logs — which is exactly
    what this does deliberately, minus the noisy traceback on a mail outage.
    """
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        password_reset_service.request_reset(db, email, requested_ip=client_ip)
    except Exception as exc:
        logger.warning(
            "Password reset request failed: %s: %s", type(exc).__name__, exc
        )
    finally:
        db.close()


@public_router.post("/reset-password")
def reset_password(
    data: ResetPasswordRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Redeem a reset link and set the new password.

    Deliberately does NOT sign the caller in. Proving control of a mailbox is
    not the same as proving control of the account, and a reset that lands
    you straight into a live session turns a forwarded email into a full
    takeover. They get a login form, which their new password opens.
    """
    try:
        user = password_reset_service.consume_token(
            db, data.token, data.new_password
        )
    except password_reset_service.ResetTokenInvalid:
        # One message for unknown / expired / already-used. Distinguishing
        # them tells a prober whether a token ever existed for the account.
        raise HTTPException(
            status_code=400,
            detail="This reset link is no longer valid. Please request a new one.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Belt and braces: `consume_token` moved `password_set_at`, which already
    # revokes every JWT minted before it. Clearing the cookie too means the
    # browser that just reset does not sit on a dead token and get a
    # mid-session bounce on its next click.
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    logger.info("Password reset redeemed for %s", user.email)
    return {"message": "Password updated. You can sign in with it now."}
