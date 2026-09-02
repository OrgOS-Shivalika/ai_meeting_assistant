from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import User
from app.dependencies.auth import get_current_user, token_claims
from app.services import admin_service, auth_service, permissions
from app.schemas.admin_schema import PasswordChangeRequest
from app.schemas.auth_schema import UserCreate, UserLogin, Token
from app.config.settings import settings

# Two routers, same `/auth` sub-path, mounted under different top-level
# prefixes in main.py:
#   public_router → PUBLIC_PREFIX  (register + login — no JWT required)
#   router        → API_PREFIX     (me + logout — authenticated session)
public_router = APIRouter(prefix="/auth", tags=["Authentication"])
router = APIRouter(prefix="/auth", tags=["Authentication"])


def _set_auth_cookie(response: Response, token: str, remember: bool = True) -> None:
    """Attach the session JWT as an HttpOnly cookie.

    HttpOnly + SameSite is the whole point of the move off localStorage:
    the browser sends it automatically on same-origin requests and the WS
    handshake, but no page script can read it, so an XSS payload can't
    steal the session. Secure/SameSite come from settings so a dev on
    http://localhost and an HTTPS deployment can both work.

    `remember` is the login form's "Keep me signed in". Omitting `max_age`
    (and `expires`) is what makes a cookie a SESSION cookie — the browser
    drops it when it closes. With `max_age` set it survives, which is what
    the checkbox is asking for. The token's own 7-day TTL is unchanged
    either way: this decides how long the BROWSER keeps the cookie, not how
    long the credential stays valid.

    Until now the checkbox was wired to nothing and everyone got the
    persistent cookie, so ticking it off on a shared machine did not
    actually sign you out when you closed the browser."""
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.AUTH_COOKIE_MAX_AGE if remember else None,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )


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
