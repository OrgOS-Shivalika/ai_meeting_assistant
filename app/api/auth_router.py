from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import User
from app.dependencies.auth import get_current_user
from app.services import auth_service
from app.schemas.auth_schema import UserCreate, UserLogin, Token
from app.config.settings import settings

# Two routers, same `/auth` sub-path, mounted under different top-level
# prefixes in main.py:
#   public_router → PUBLIC_PREFIX  (register + login — no JWT required)
#   router        → API_PREFIX     (me + logout — authenticated session)
public_router = APIRouter(prefix="/auth", tags=["Authentication"])
router = APIRouter(prefix="/auth", tags=["Authentication"])


def _set_auth_cookie(response: Response, token: str) -> None:
    """Attach the session JWT as an HttpOnly cookie.

    HttpOnly + SameSite is the whole point of the move off localStorage:
    the browser sends it automatically on same-origin requests and the WS
    handshake, but no page script can read it, so an XSS payload can't
    steal the session. Secure/SameSite come from settings so a dev on
    http://localhost and an HTTPS deployment can both work."""
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.AUTH_COOKIE_MAX_AGE,
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
    token = auth_service.create_token({"user_id": str(user.id)})
    _set_auth_cookie(response, token)
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
def get_me(user: User = Depends(get_current_user)):
    """Return the authenticated user plus their organization. The frontend
    uses this to render identity in the sidebar and gate org-scoped actions."""
    org = user.organization
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "google_profile_picture": user.google_profile_picture,
        "organization": {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
        } if org else None,
    }
