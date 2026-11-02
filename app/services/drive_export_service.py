"""Google Drive transcript export — one Google Doc per meeting.

A user who clicks "Connect Google Drive" grants `drive.file`; on connect we
create a "Meeting Transcripts" folder in their Drive (`users.drive_folder_id`).
After the post-meeting pipeline, every completed meeting is written there as
a Doc named `YYYY-MM-DD <Buyer/Company> - <Topic>` (just `YYYY-MM-DD <Topic>`
when no buyer is named) holding the attendees, the
notes (summary, decisions, action items) and the full transcript.

Recipients: the meeting owner, plus any org member whose email is on the
calendar invite — each with Drive connected. Display names are never used.

`drive.file` only reaches files this app created, so the folder can be
renamed or moved by the user and keeps working. Re-running an export
updates the same Doc (`meetings.drive_files[user_id]`), never a second one.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import timedelta, timezone

import requests

from app.db.models import Meeting, Participant, Task, User

logger = logging.getLogger(__name__)

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_NAME = "Meeting Transcripts"
IST = timezone(timedelta(hours=5, minutes=30))   # ponytail: one org, IST, no DST; per-org tz if a second region shows up
API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"

NAME_SYSTEM = """You name meeting files. From the meeting title, summary, attendees and the start of
the transcript (may be Hindi/Hinglish) return JSON {"company": "..." or null, "topic": "..."}.
- company: the buyer, customer or brand the meeting is about, exactly as named in the
  meeting (e.g. "Anko Kmart"). Only a name actually said or written — never guess.
  null if none is named.
- topic: what the meeting was about in at most 8 words, in English, using the meeting's
  own terms (e.g. "SS27 cushion cover BCI"). No dates, no company name."""
TRANSCRIPT_CHARS = 8000   # buyers are usually named early; the summary covers the rest


class DriveAccessLost(Exception):
    """Token lacks Drive permission or the user revoked it — reconnect needed, retrying won't help."""


def folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def doc_url(file_id: str) -> str:
    return f"https://docs.google.com/document/d/{file_id}/edit"


# ─── Drive HTTP ──────────────────────────────────────────────────────────────

def _token(user) -> str:
    from app.services.google_calendar_service import _get_valid_credentials
    return _get_valid_credentials(user).token


def _check(resp):
    if resp.status_code in (401, 403):
        raise DriveAccessLost(f"{resp.status_code} {resp.text[:200]}")
    resp.raise_for_status()
    return resp.json()


def _multipart(meta: dict, text: str):
    b = "drive_export_boundary_7f3a"
    body = (
        f"--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
        f"--{b}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n"
    ).encode() + text.encode("utf-8") + f"\r\n--{b}--".encode()
    return body, f"multipart/related; boundary={b}"


def ensure_folder(user) -> str:
    """Return the user's transcripts folder id, creating it if missing or trashed."""
    h = {"Authorization": f"Bearer {_token(user)}"}
    if user.drive_folder_id:
        r = requests.get(f"{API}/{user.drive_folder_id}", headers=h, params={"fields": "id,trashed"}, timeout=15)
        if r.status_code == 200 and not r.json().get("trashed"):
            return user.drive_folder_id
    r = requests.post(API, headers=h, timeout=15, json={
        "name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"})
    return _check(r)["id"]


def upload_doc(user, folder_id: str, name: str, text: str, file_id: str | None = None) -> str:
    """Create (or update in place) a Google Doc from plain text. Returns the file id."""
    h = {"Authorization": f"Bearer {_token(user)}"}
    if file_id:
        body, ctype = _multipart({"name": name}, text)
        r = requests.patch(f"{UPLOAD}/{file_id}", params={"uploadType": "multipart"},
                           headers={**h, "Content-Type": ctype}, data=body, timeout=60)
        if r.status_code != 404:   # 404 = the user deleted it; make a new one
            return _check(r)["id"]
    body, ctype = _multipart(
        {"name": name, "mimeType": "application/vnd.google-apps.document", "parents": [folder_id]}, text)
    r = requests.post(UPLOAD, params={"uploadType": "multipart"},
                      headers={**h, "Content-Type": ctype}, data=body, timeout=60)
    return _check(r)["id"]


# ─── Content ─────────────────────────────────────────────────────────────────

def _local_date(meeting):
    dt = meeting.started_at or meeting.created_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def name_parts(meeting, attendees, client=None) -> tuple[str | None, str]:
    """(company, topic) for the file name. Falls back to (None, title) on any failure."""
    title = meeting.title or "Meeting"
    try:
        if client is None:
            from app.ai_agents.openAI_transcript_analyzer import _get_client
            client = _get_client()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": NAME_SYSTEM},
                      {"role": "user", "content": json.dumps({
                          "title": title, "summary": (meeting.summary or "")[:4000],
                          "attendees": attendees,
                          "transcript_start": (meeting.transcript_text or meeting.transcript or "")[:TRANSCRIPT_CHARS],
                      }, ensure_ascii=False)}],
            response_format={"type": "json_object"}, temperature=0, timeout=30,
        )
        out = json.loads(resp.choices[0].message.content)
        company, topic = (out.get("company") or "").strip(), (out.get("topic") or "").strip()
        if company.lower() in ("null", "none", "internal", "n/a", "unknown"):
            company = ""
        return (company or None), (topic or title)
    except Exception as exc:
        logger.warning("Drive export: naming call failed for meeting %s: %s", meeting.id, exc)
        return None, title


def file_name(meeting, company: str | None, topic: str) -> str:
    topic = topic[:1].upper() + topic[1:]
    rest = f"{company} - {topic}" if company else topic
    rest = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", rest)
    rest = re.sub(r"\s+", " ", rest).strip()[:110]
    return f"{_local_date(meeting):%Y-%m-%d} {rest}"


def build_text(meeting, name, participants, tasks, decisions=None) -> str:
    d = _local_date(meeting)
    lines = [name, "",
             f"Date: {d:%Y-%m-%d %H:%M} IST"
             + (f" · Duration: {meeting.duration_minutes} min" if meeting.duration_minutes else "")
             + (f" · Platform: {meeting.meeting_platform}" if meeting.meeting_platform else ""),
             "", "ATTENDEES"]
    seen = set()
    for p in participants:
        if not p.name or p.name in seen:
            continue
        seen.add(p.name)
        org = " (organizer)" if str(p.is_organizer).lower() in ("true", "1") else ""
        lines.append(f"- {p.name}{f' <{p.email}>' if p.email else ''}{org}")
    if not seen:
        lines.append("- (not recorded)")

    lines += ["", "NOTES", "", "Summary", meeting.summary or "(no summary)"]
    if decisions:
        lines += ["", "Decisions"] + [f"- {x}" for x in decisions]
    if tasks:
        lines += ["", "Action items"]
        for t in tasks:
            extra = ", ".join(x for x in (
                t.owner_name, f"due {t.due_date:%Y-%m-%d}" if t.due_date else None) if x)
            lines.append(f"- {t.task}{f' ({extra})' if extra else ''}")
    lines += ["", "TRANSCRIPT", "", meeting.transcript_text or meeting.transcript or "(no transcript)"]
    return "\n".join(lines)


# ─── Orchestration ───────────────────────────────────────────────────────────

def recipients(db, meeting) -> list:
    """Owner + org members on the calendar invite, who have Drive connected."""
    emails = {(a.get("email") or "").lower()
              for a in ((meeting.google_event_data or {}).get("attendees") or []) if a.get("email")}
    q = db.query(User).filter(
        User.organization_id == meeting.organization_id,
        User.drive_folder_id.isnot(None),
        User.google_access_token.isnot(None),
    )
    return [u for u in q if u.id == meeting.user_id or (u.email or "").lower() in emails]


def export_meeting(db, meeting_id: int, decisions=None, only_user_id=None, client=None) -> dict:
    """Write this meeting's Doc to every recipient's folder.

    Returns {"uploaded": n, "skipped": reason?}. Raises if any upload failed for a
    transient reason, after trying everyone, so the Celery task retries; a
    retry is safe because each recipient's Doc is updated in place."""
    meeting = db.get(Meeting, meeting_id)
    if not meeting or not (meeting.transcript_text or meeting.transcript):
        return {"uploaded": 0, "skipped": "no transcript"}
    users = recipients(db, meeting)
    if only_user_id:
        users = [u for u in users if str(u.id) == str(only_user_id)]
    if not users:
        return {"uploaded": 0, "skipped": "no recipient with Drive connected"}

    participants = db.query(Participant).filter(Participant.meeting_id == meeting.id).all()
    tasks = db.query(Task).filter(Task.meeting_id == meeting.id).order_by(Task.id).all()
    company, topic = name_parts(meeting, sorted({p.name for p in participants if p.name}), client)
    name = file_name(meeting, company, topic)
    text = build_text(meeting, name, participants, tasks, decisions)

    uploaded, failed = 0, []
    for u in users:
        try:
            folder = ensure_folder(u)
            if folder != u.drive_folder_id:
                u.drive_folder_id = folder
                db.commit()
            files = dict(meeting.drive_files or {})
            files[str(u.id)] = upload_doc(u, folder, name, text, files.get(str(u.id)))
            meeting.drive_files = files
            db.commit()
            uploaded += 1
        except DriveAccessLost as exc:
            db.rollback()
            logger.warning("Drive export: %s lost Drive access, skipping (reconnect needed): %s", u.email, exc)
        except Exception as exc:
            db.rollback()
            failed.append(u.email)
            logger.error("Drive export failed for meeting %s → %s: %s", meeting.id, u.email, exc)
    logger.info("📁 Drive export meeting=%s name=%r uploaded=%d failed=%s", meeting.id, name, uploaded, failed)
    if failed:
        raise RuntimeError(f"Drive upload failed for {failed}")
    return {"uploaded": uploaded, "name": name}
