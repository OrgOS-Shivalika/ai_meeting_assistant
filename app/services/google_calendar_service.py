from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import User
from datetime import datetime, timedelta, timezone
import uuid
import requests
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _build_credentials(user) -> Credentials:
    """Legacy: kept as an alias for _get_valid_credentials since some old
    callers might still be around. New code should call
    `_get_valid_credentials(user)` directly."""
    return _get_valid_credentials(user)


def _get_valid_credentials(user) -> Credentials:
    """Build a `google.oauth2.credentials.Credentials` from the user row,
    refreshing the access token if it's expired (or missing an expiry)
    and persisting the refreshed token + new expiry back to the DB.

    Without this, stored access tokens age out after ~60 min and every
    subsequent API call silently fails — forcing users to reconnect
    Google Calendar by hand. The `access_type=offline` we ask for on
    the OAuth flow already gives us the refresh_token needed here.

    Idempotent: if the token isn't expired, no network call is made
    and the DB row is left alone.
    """
    creds = Credentials(
        token=user.google_access_token,
        refresh_token=user.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )
    # Seed the expiry from the DB so `.expired` returns the truth.
    # `Credentials.expiry` must be NAIVE UTC (per the google-auth docs);
    # our DB column is timezone-aware, so strip it.
    stored_expiry = getattr(user, "google_token_expires_at", None)
    if stored_expiry is not None:
        if stored_expiry.tzinfo is not None:
            stored_expiry = stored_expiry.astimezone(timezone.utc).replace(tzinfo=None)
        creds.expiry = stored_expiry

    # Refresh when we're past (or within 60s of) expiry AND we still
    # have a refresh_token.
    if creds.refresh_token and (creds.expired or creds.expiry is None):
        try:
            creds.refresh(GoogleAuthRequest())
        except Exception as exc:
            # `invalid_grant` at refresh time means the refresh_token
            # itself is dead — user revoked access, the OAuth app is in
            # Testing mode and hit the 7-day expiry, the account
            # changed passwords, etc. Nothing we can do server-side;
            # the user MUST reconnect. Wipe the dead tokens so:
            #   1) the /auth/google/status endpoint honestly reports
            #      "not connected" instead of lying,
            #   2) subsequent sync ticks don't hit the same wall every
            #      2 minutes generating log noise.
            msg = str(exc)
            if "invalid_grant" in msg.lower() or "expired or revoked" in msg.lower():
                logger.warning(
                    "Clearing dead Google tokens for %s — refresh returned "
                    "invalid_grant. User must reconnect via /integrations.",
                    getattr(user, "email", "?"),
                )
                db = SessionLocal()
                try:
                    db.query(User).filter(User.id == user.id).update(
                        {
                            "google_access_token": None,
                            "google_refresh_token": None,
                            "google_token_expires_at": None,
                        },
                        synchronize_session=False,
                    )
                    db.commit()
                    user.google_access_token = None
                    user.google_refresh_token = None
                    user.google_token_expires_at = None
                except Exception as clear_exc:
                    db.rollback()
                    logger.error(
                        "Failed to clear dead Google tokens for %s: %s",
                        getattr(user, "email", "?"), clear_exc,
                    )
                finally:
                    db.close()
            else:
                logger.warning(
                    "Google token refresh failed for user %s: %s",
                    getattr(user, "email", "?"), exc,
                )
            raise

        # Persist the new access token + expiry. Do it on a fresh
        # session so we don't stomp on whatever session the caller may
        # be holding. `updated_at` is auto-managed by the User model.
        db = SessionLocal()
        try:
            db.query(User).filter(User.id == user.id).update(
                {
                    "google_access_token": creds.token,
                    "google_token_expires_at": (
                        creds.expiry.replace(tzinfo=timezone.utc)
                        if creds.expiry
                        else None
                    ),
                },
                synchronize_session=False,
            )
            db.commit()
            # Reflect back onto the passed-in object so any code that
            # reads user.google_access_token later in the same request
            # sees the fresh value.
            user.google_access_token = creds.token
            if creds.expiry:
                user.google_token_expires_at = creds.expiry.replace(tzinfo=timezone.utc)
            logger.info(
                "Refreshed Google token for %s (expiry=%s)",
                getattr(user, "email", "?"),
                creds.expiry,
            )
        except Exception as exc:
            db.rollback()
            logger.error(
                "Failed to persist refreshed Google token for %s: %s",
                getattr(user, "email", "?"), exc,
            )
        finally:
            db.close()

    return creds


def _to_rfc3339(dt: datetime) -> str:
    """Google Calendar wants RFC3339. Naive datetimes are treated as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _create_open_meet_space(user) -> dict | None:
    """Create a fresh Meet space with `accessType=OPEN` via the Meet REST API.

    Spaces created here are owned by our app's token, so we can configure them
    freely (unlike Meet conferences spun up by Calendar's
    `conferenceData.createRequest`, which only the Calendar UI can manage).
    Returns the space dict (with `meetingUri`, `meetingCode`, `name`) or None
    on failure.
    Requires the `meetings.space.created` scope on the user's token.
    """
    if not getattr(user, "google_access_token", None):
        return None
    # Refresh + persist before hitting the raw Meet REST API — this path
    # bypasses googleapiclient's auto-refresh entirely.
    try:
        creds = _get_valid_credentials(user)
    except Exception:
        return None
    url = "https://meet.googleapis.com/v2/spaces"
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }
    payload = {"config": {"accessType": "OPEN"}}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code >= 400:
            logger.warning(
                "Could not create OPEN Meet space for %s: %s %s",
                getattr(user, "email", "?"),
                resp.status_code,
                resp.text[:300],
            )
            return None
        space = resp.json()
        logger.info(
            "Created OPEN Meet space %s for %s",
            space.get("name") or space.get("meetingCode"),
            getattr(user, "email", "?"),
        )
        return space
    except Exception as e:
        logger.error(
            "Error creating OPEN Meet space for %s: %s",
            getattr(user, "email", "?"),
            e,
        )
        return None


def create_calendar_event(
    user,
    *,
    title: str,
    scheduled_at: datetime,
    duration_minutes: int | None = 30,
    description: str | None = None,
    meeting_url: str | None = None,
    attendees: list[str] | None = None,
    request_meet_link: bool = True,
):
    """Create an event on the user's primary Google Calendar.

    If `meeting_url` is None and `request_meet_link` is True, a Google Meet
    conference is auto-generated and its hangoutLink is returned on the event.
    Returns the inserted event dict, or None if the user has no Google
    credentials or the API call fails (logs the error in that case).
    """
    if not getattr(user, "google_access_token", None):
        logger.info(
            f"User {getattr(user, 'email', '?')} has no Google access token; "
            "skipping calendar event creation."
        )
        return None

    try:
        creds = _build_credentials(user)
        service = build("calendar", "v3", credentials=creds)

        end_time = scheduled_at + timedelta(minutes=duration_minutes or 30)
        body: dict = {
            "summary": title,
            "start": {"dateTime": _to_rfc3339(scheduled_at)},
            "end": {"dateTime": _to_rfc3339(end_time)},
        }
        if description:
            body["description"] = description
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees if e]

        insert_kwargs = {"calendarId": "primary", "body": body}

        # When the caller wants a Meet link and didn't supply one, prefer to
        # create the space via the Meet API so we own it and can set
        # accessType=OPEN at creation time. The Meet space is then attached to
        # the event as a pre-existing conference. Falling back to Calendar's
        # `conferenceData.createRequest` only happens if the Meet API call
        # fails (e.g. consumer Gmail account, scope missing) — those default
        # spaces are not OPEN and the bot may need to be admitted manually.
        open_meet_space = None
        if not meeting_url and request_meet_link:
            open_meet_space = _create_open_meet_space(user)
            if open_meet_space:
                meet_uri = open_meet_space.get("meetingUri")
                meet_code = open_meet_space.get("meetingCode")
                if meet_uri:
                    meeting_url = meet_uri
                    body["conferenceData"] = {
                        "conferenceId": meet_code or meet_uri,
                        "conferenceSolution": {
                            "key": {"type": "hangoutsMeet"},
                            "name": "Google Meet",
                        },
                        "entryPoints": [
                            {
                                "entryPointType": "video",
                                "uri": meet_uri,
                                "label": meet_uri.replace("https://", ""),
                            }
                        ],
                    }
                    insert_kwargs["conferenceDataVersion"] = 1

        if meeting_url:
            existing_desc = body.get("description", "")
            join_line = f"Join: {meeting_url}"
            body["description"] = (
                f"{existing_desc}\n\n{join_line}".strip()
                if existing_desc
                else join_line
            )
        elif request_meet_link:
            # Fallback: Meet API space create failed, ask Calendar to spin up
            # a default Meet conference (won't be OPEN, but better than no
            # link at all).
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
            insert_kwargs["conferenceDataVersion"] = 1

        event = service.events().insert(**insert_kwargs).execute()
        logger.info(
            f"Created Google Calendar event {event.get('id')} for user {user.email}"
        )

        # The caller pulls the URL out of `event['hangoutLink']`. When we
        # attached a pre-created Meet space, Calendar may not populate that
        # field, so set it explicitly so downstream code is uniform.
        if open_meet_space and not event.get("hangoutLink"):
            uri = open_meet_space.get("meetingUri")
            if uri:
                event["hangoutLink"] = uri

        return event
    except Exception as e:
        logger.error(
            f"Failed to create calendar event for user {getattr(user, 'email', '?')}: {e}"
        )
        return None


def get_calendar_events(user):
    if not user.google_access_token:
        logger.warning(f"User {user.email} has no Google access token")
        return []

    creds = _build_credentials(user)

    try:
        service = build("calendar", "v3", credentials=creds)

        events = service.events().list(
            calendarId="primary",
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
            timeMin=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ).execute()

        return events.get("items", [])
    except Exception as e:
        logger.error(f"Error fetching calendar events for {user.email}: {str(e)}")
        return []

def get_google_user_info(user):
    if not user.google_access_token:
        return None

    try:
        creds = _get_valid_credentials(user)
        url = "https://www.googleapis.com/oauth2/v3/userinfo"
        headers = {"Authorization": f"Bearer {creds.token}"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching Google user info for {user.email}: {str(e)}")
        return None