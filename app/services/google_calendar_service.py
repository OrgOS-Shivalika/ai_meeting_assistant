from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from app.config.settings import settings
from datetime import datetime, timedelta, timezone
import uuid
import requests
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _build_credentials(user):
    return Credentials(
        token=user.google_access_token,
        refresh_token=user.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )


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
    url = "https://meet.googleapis.com/v2/spaces"
    headers = {
        "Authorization": f"Bearer {user.google_access_token}",
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
        url = "https://www.googleapis.com/oauth2/v3/userinfo"
        headers = {"Authorization": f"Bearer {user.google_access_token}"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching Google user info for {user.email}: {str(e)}")
        return None