"""Email delivery for notifications, and the due-soon sweep.

Two tasks, both on a timer rather than triggered per event:

`send_pending_notification_emails` scans for rows created but not yet emailed
and sends them. A queue-per-event would be more immediate, but this shape has
a property that matters more here: **the notification row is written in the
caller's transaction, and the email is a separate concern that can retry.** If
SMTP is down for ten minutes, nothing is lost — the rows are still there,
unemailed, and the next pass picks them up.

**Deployment trap, and it is silent:** these run on the WORKER, so the worker
needs `SMTP_*` and `APP_PUBLIC_URL`. Without `SMTP_HOST`,
`mail_service.is_configured()` returns False and logs "skipped" as a SUCCESS —
no mail is sent and nothing errors. Set the mail env on the worker service,
not just on web.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from app.celery_app import celery
from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import Notification, Task, User
from app.services import mail_service, notifications
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

#: How far ahead "due soon" looks. A day is the useful window for a task
#: board: far enough to act on, near enough that the reminder is not noise.
DUE_SOON_HOURS = 24

#: Don't email a notification that has been sitting unsent for ages — after an
#: outage that would deliver a burst of stale news. The rows stay for the
#: in-app feed either way; only the interruption is dropped.
MAX_EMAIL_AGE_HOURS = 24

_SUBJECT = {
    notifications.KIND_ASSIGNED: "You've been assigned a task",
    notifications.KIND_MENTIONED: "You were mentioned in a comment",
    notifications.KIND_DUE_SOON: "A task is due soon",
}


def _board_url(task_id: int) -> str:
    return f"{settings.APP_PUBLIC_URL.rstrip('/')}/boards?task={task_id}"


def _body(note: Notification) -> tuple[str, str]:
    payload = note.payload or {}
    title = payload.get("task") or "a task"
    actor = payload.get("actor_name") or "Someone"
    url = _board_url(note.task_id) if note.task_id else settings.APP_PUBLIC_URL

    if note.kind == notifications.KIND_ASSIGNED:
        lead = f"{actor} assigned you a task."
    elif note.kind == notifications.KIND_MENTIONED:
        excerpt = (payload.get("excerpt") or "").strip()
        lead = f"{actor} mentioned you in a comment."
        if excerpt:
            lead += f'\n\n  "{excerpt}"'
    else:
        lead = f"This task is due {payload.get('due_date') or 'soon'}."

    text = f"""{lead}

  {title}

Open it: {url}

You can turn these emails off in Settings. The in-app bell keeps working
either way.
"""
    html = f"""<p style="margin:0 0 12px;font-size:14px;color:#374151;">{lead}</p>
<p style="margin:0 0 16px;font-size:15px;font-weight:600;color:#0f1523;">{title}</p>
<a href="{url}" style="display:inline-block;background:#4f46e5;color:#fff;font-size:14px;
   font-weight:600;text-decoration:none;padding:10px 18px;border-radius:8px;">Open the task</a>
<p style="margin:16px 0 0;font-size:12px;color:#6b7280;">
  You can turn these emails off in Settings. The in-app bell keeps working either way.
</p>"""
    return text, html


@celery.task(name="meeting_ai.send_pending_notification_emails", bind=True)
def send_pending_notification_emails(self):
    """Email every notification that has not been emailed yet."""
    db = SessionLocal()
    sent = skipped = 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_EMAIL_AGE_HOURS)
        pending = (
            db.query(Notification)
            .filter(
                Notification.emailed_at.is_(None),
                Notification.created_at >= cutoff,
            )
            .order_by(Notification.created_at.asc())
            .limit(200)
            .all()
        )
        for note in pending:
            user = db.query(User).filter(User.id == note.user_id).first()
            if user is None:
                note.emailed_at = datetime.now(timezone.utc)  # nothing to send to
                continue
            if not notifications.wants_email(user, note.kind):
                # Stamped as handled so it is not reconsidered every pass. The
                # row stays in their in-app feed — opting out of email is not
                # opting out of knowing.
                note.emailed_at = datetime.now(timezone.utc)
                skipped += 1
                continue
            text, html = _body(note)
            result = mail_service.send_email(
                to=user.email,
                subject=_SUBJECT.get(note.kind, "Update on your work"),
                text_body=text,
                html_body=html,
            )
            # Stamp on skipped/failed too. Retrying a failed send forever
            # would turn one broken address into an infinite loop; the row
            # remains visible in-app, which is the fallback that matters.
            note.emailed_at = datetime.now(timezone.utc)
            sent += 1 if result.sent else 0
        db.commit()
        logger.info(
            "Notification emails: %d sent, %d opted out, %d considered",
            sent, skipped, len(pending),
        )
        return {"sent": sent, "opted_out": skipped, "considered": len(pending)}
    except Exception as exc:
        db.rollback()
        logger.error("Notification email sweep failed: %s", exc)
        raise
    finally:
        db.close()


@celery.task(name="meeting_ai.notify_tasks_due_soon", bind=True)
def notify_tasks_due_soon(self):
    """Raise a due-soon notification for assigned, unfinished, imminent tasks.

    Only tasks with a REAL assignee — `owner_name` is free text and there is
    nobody to send to. That is the whole reason assignment had to land first.

    Safe to run often: `notify_due_soon` dedupes on (task, due date), so
    repeated passes create nothing new, while a genuinely rescheduled task can
    remind once more.
    """
    db = SessionLocal()
    created = 0
    try:
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(hours=DUE_SOON_HOURS)
        due = (
            db.query(Task)
            .filter(
                Task.assignee_user_id.isnot(None),
                Task.due_date.isnot(None),
                Task.due_date <= horizon,
                Task.due_date >= now - timedelta(days=1),  # not long-overdue spam
                or_(Task.is_completed == 0, Task.is_completed.is_(None)),
                Task.status != "archived",
            )
            .all()
        )
        for task in due:
            if notifications.notify_due_soon(db, task, task.assignee_user_id):
                created += 1
        db.commit()
        logger.info("Due-soon sweep: %d task(s) in window, %d new notification(s)",
                    len(due), created)
        return {"in_window": len(due), "created": created}
    except Exception as exc:
        db.rollback()
        logger.error("Due-soon sweep failed: %s", exc)
        raise
    finally:
        db.close()
