import secrets

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.services.google_service import SCOPES
from app.services.drive_export_service import DRIVE_SCOPE
from app.services import google_auth_service
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
def login(request: Request, drive: bool = False, user=Depends(get_current_user)):
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
        # Drive is optional: asked for only from "Connect Google Drive", and
        # kept on every later reconnect so a Calendar reconnect can't drop it.
        "scope":" ".join(SCOPES + ([DRIVE_SCOPE] if drive or user.drive_folder_id else [])),
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

        google_auth_service.persist_google_tokens(
            db,
            user,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            profile=profile,
        )

        logger.info(f"Post-commit check - User: {user.email}, AT set: {bool(user.google_access_token)}")

        drive_connected = google_auth_service.sync_drive_folder(
            db, user, DRIVE_SCOPE in (tokens.get("scope") or "").split()
        )
        return {"message": "Google connected", "is_connected": True, "drive_connected": drive_connected}

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
    return google_auth_service.disconnect_google(db, user)

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

# ─── Google Drive transcript export ─────────────────────────────────────────

@router.get("/drive/status")
def drive_status(user=Depends(get_current_user)):
    from app.services.drive_export_service import folder_url
    connected = bool(user.drive_folder_id and user.google_access_token)
    return {
        "connected": connected,
        "folder_url": folder_url(user.drive_folder_id) if connected else None,
    }


@router.post("/drive/disconnect")
def drive_disconnect(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Stop exporting. Calendar stays connected; the folder and its Docs stay in Drive."""
    user.drive_folder_id = None
    db.commit()
    return {"connected": False}


@router.post("/drive/export-past")
def drive_export_past(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Queue an export of every completed meeting of this user that isn't in
    their Drive yet — the same meetings new exports cover (owner or invited)."""
    from app.db.models import Meeting
    from app.celery_tasks.meeting_tasks import export_meeting_to_drive
    if not user.drive_folder_id:
        raise HTTPException(status_code=400, detail="Connect Google Drive first")
    email = (user.email or "").lower()
    rows = db.query(Meeting).filter(
        Meeting.organization_id == user.organization_id,
        Meeting.status == "completed",
    ).all()
    queued = 0
    for m in rows:
        invited = any((a.get("email") or "").lower() == email
                      for a in ((m.google_event_data or {}).get("attendees") or []))
        if (m.user_id == user.id or invited) and str(user.id) not in (m.drive_files or {}):
            export_meeting_to_drive.delay(m.id, only_user_id=str(user.id))
            queued += 1
    return {"queued": queued}


@router.get("/drive/meeting/{meeting_id}")
def drive_meeting_link(meeting_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """The current user's own Doc for this meeting, if one was exported."""
    from app.db.models import Meeting
    from app.services.drive_export_service import doc_url
    m = db.get(Meeting, meeting_id)
    file_id = ((m.drive_files or {}) if m and m.organization_id == user.organization_id else {}).get(str(user.id))
    return {"url": doc_url(file_id) if file_id else None}
