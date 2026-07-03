import secrets

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import User
from app.services.google_service import SCOPES
from app.dependencies.auth import get_current_user
from app.utils.logger import setup_logger
from app.config.settings import settings
import requests
from urllib.parse import urlencode

logger = setup_logger(__name__)

router = APIRouter(prefix="/auth/google")


def _allowed_origins() -> set[str]:
    """Origins the app trusts to be a legitimate frontend host — reuses
    CORS_ORIGINS so there's ONE source of truth. When you add a new
    ngrok/tunnel URL, add it to CORS_ORIGINS and both CORS + OAuth follow.
    settings.CORS_ORIGINS is already a list (split at load time)."""
    raw = getattr(settings, "CORS_ORIGINS", None) or []
    return {str(o).strip().rstrip("/") for o in raw if str(o).strip()}


def _pick_redirect_uri(request: Request) -> str:
    """Derive the OAuth redirect_uri from the current request so a manager
    hitting the ngrok URL gets sent back to ngrok, and a dev on localhost
    gets sent back to localhost.

    Same-origin GETs often omit the Origin header, so we ALSO look at
    Host / X-Forwarded-Host (set by ngrok / any reverse proxy). Falls
    back to settings.GOOGLE_REDIRECT_URI when nothing usable is present
    (server-to-server call, curl without headers).

    '*' in the allow-list is treated as "trust any origin". Google
    itself enforces redirect_uri against the registered list in Cloud
    Console, so an attacker origin just makes Google reject the flow —
    no credential leak."""
    allowed = _allowed_origins()

    # 1. Origin header — most reliable when browsers send it (POSTs,
    #    cross-origin fetches, some GETs).
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin and ("*" in allowed or origin in allowed):
        return f"{origin}/auth/google/callback"

    # 2. Host / X-Forwarded-Host — always present, and ngrok/cloud
    #    proxies populate X-Forwarded-Host with the public host. Combine
    #    with X-Forwarded-Proto (or default to https for non-localhost).
    fwd_host = (request.headers.get("x-forwarded-host") or "").strip()
    fwd_proto = (request.headers.get("x-forwarded-proto") or "").strip()
    host = fwd_host or (request.headers.get("host") or "").strip()
    if host:
        if fwd_proto:
            scheme = fwd_proto
        elif "localhost" in host or host.startswith("127.") or host.startswith("0.0.0.0"):
            scheme = "http"
        else:
            scheme = "https"
        derived = f"{scheme}://{host}"
        if "*" in allowed or derived in allowed:
            return f"{derived}/auth/google/callback"

    return settings.GOOGLE_REDIRECT_URI


@router.get("/login")
def login(request: Request):
    redirect_uri = _pick_redirect_uri(request)
    logger.info(
        "Google /login origin=%r host=%r x-fwd-host=%r x-fwd-proto=%r allowed=%s -> redirect_uri=%s",
        request.headers.get("origin"),
        request.headers.get("host"),
        request.headers.get("x-forwarded-host"),
        request.headers.get("x-forwarded-proto"),
        sorted(_allowed_origins()),
        redirect_uri,
    )
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "prompt":"consent",        # 🔥 forces re-consent
        "access_type":"offline",   # 🔥 ensures refresh_token
        "include_granted_scopes":"false",  # 🔥 VERY IMPORTANT
        "response_type":"code",
        "scope":" ".join(SCOPES),
        "state": secrets.token_urlsafe(24),
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return {"auth_url": auth_url}


@router.get("/exchange-code")
def exchange_code(
    request: Request,
    code: str = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
        
    logger.info(f"--- START TOKEN EXCHANGE ---")
    logger.info(f"User from JWT: {user.email} (ID: {user.id})")
    
    try:
        # Manual exchange using requests to avoid PKCE/state issues.
        # redirect_uri MUST exactly match the one Google saw at /login —
        # so we derive it from the current Origin header the same way.
        redirect_uri = _pick_redirect_uri(request)
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }

        logger.info(f"Exchanging code with redirect_uri: {redirect_uri}")
        response = requests.post(token_url, data=data)
        tokens = response.json()
        
        if response.status_code != 200:
            logger.error(f"Google Token Exchange Failed: {tokens}")
            raise HTTPException(status_code=400, detail=f"Google Error: {tokens.get('error_description', 'Unknown error')}")

        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in") # seconds
        
        expires_at = None
        if expires_in:
            from datetime import datetime, timedelta, timezone
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        if not access_token:
            logger.error("No access token received from Google")
            raise HTTPException(status_code=400, detail="No access token received")

        # Fetch profile info immediately to cache it
        profile_response = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        profile = profile_response.json() if profile_response.status_code == 200 else {}

        logger.info(f"Google tokens fetched successfully. Refresh token present: {bool(refresh_token)}")

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
        logger.info(f"Post-commit check - User: {user.email}, AT set: {bool(user.google_access_token)}")
        
        return {"message": "Google connected", "is_connected": True}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"FATAL ERROR in exchange_code: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
    finally:
        logger.info(f"--- END TOKEN EXCHANGE ---")

@router.post("/disconnect")
def disconnect_google(
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
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

@router.get("/status")
def get_google_status(user=Depends(get_current_user)):
    from app.services.google_calendar_service import get_google_user_info
    google_info = get_google_user_info(user)
    return {
        "is_connected": bool(user.google_access_token),
        "email": user.email,
        "google_info": google_info
    }

@router.get("/events")
def get_events(user=Depends(get_current_user)):
    from app.services.google_calendar_service import get_calendar_events
    events = get_calendar_events(user)
    return events