"""Telling people that something happened to their work.

Before this, @mentions produced a red dot you only saw if you were already
looking at the board, and assignment produced no signal at all. For a product
whose premise is capturing work while you are NOT paying attention, that is
backwards.

The rules that matter, and why:

* **Never notify yourself.** Assigning yourself a card or @mentioning yourself
  is not news. This is checked in one place rather than at each call site,
  because the call sites are the easy thing to add and the easy thing to
  forget.
* **Never notify someone who cannot open the thing.** A notification linking
  to a 403 is worse than silence — it tells them work exists and refuses to
  show it. Assignment is safe by construction (it grants access); mentions are
  not, so `mentions.py` already filters through `task_view_clause` and this
  module trusts callers to have done that.
* **Creating the row is synchronous; sending the email is not.** The row is
  the source of truth and belongs in the caller's transaction. SMTP is a
  1-2 second round trip and has no business inside a PATCH.
* **Missing preference keys mean ON.** A notification kind added next year
  should reach people, not arrive silently disabled for everyone who predates
  it.

**Deployment note that will bite otherwise:** email is dispatched from a
CELERY task, so the WORKER needs `SMTP_*` and `APP_PUBLIC_URL`. Without them
`mail_service.is_configured()` returns False and logs "skipped" as a success —
nothing is sent and nothing errors. See the handout.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Notification, Task, User
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

KIND_ASSIGNED = "task_assigned"
KIND_MENTIONED = "task_mentioned"
KIND_DUE_SOON = "task_due_soon"

#: Preference key per kind. Absent from a user's JSONB = enabled.
_PREF_KEY = {
    KIND_ASSIGNED: "email_task_assigned",
    KIND_MENTIONED: "email_task_mentioned",
    KIND_DUE_SOON: "email_task_due_soon",
}


def wants_email(user: User, kind: str) -> bool:
    """Whether this person wants EMAIL for this kind. In-app is not optional.

    In-app costs the reader nothing — it is a number on a bell they can
    ignore. Email interrupts. Only the interrupting half is opt-out, which
    keeps the feed complete for anyone who later turns email back on.
    """
    prefs = getattr(user, "notification_prefs", None) or {}
    return bool(prefs.get(_PREF_KEY.get(kind, ""), True))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create(
    db: Session,
    *,
    user_id,
    kind: str,
    actor_user_id=None,
    task_id: Optional[int] = None,
    comment_id: Optional[int] = None,
    payload: Optional[dict[str, Any]] = None,
    dedupe_key: Optional[str] = None,
) -> Optional[Notification]:
    """Record one notification. Returns it, or None if it was suppressed.

    Suppressed means: addressed to the person who caused it, or a duplicate of
    something already sent. Both are normal, so neither raises.

    Does NOT commit — the row belongs in the caller's transaction, so a
    notification can never outlive the change that justified it.
    """
    if actor_user_id is not None and str(actor_user_id) == str(user_id):
        return None  # your own action is not news

    note = Notification(
        user_id=user_id,
        kind=kind,
        actor_user_id=actor_user_id,
        task_id=task_id,
        comment_id=comment_id,
        payload=payload or {},
        dedupe_key=dedupe_key,
    )
    db.add(note)
    try:
        # Flush rather than commit: surfaces the unique violation here, where
        # it can be handled as "already notified", instead of blowing up the
        # caller's commit much later with no context.
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.debug("Notification already sent: %s / %s", user_id, dedupe_key)
        return None
    return note


def notify_assigned(db: Session, task: Task, assignee_id, actor: User) -> Optional[Notification]:
    """Someone was given a card.

    No dedupe key: being assigned the same card twice IS two events, and
    suppressing the second would hide a real handover.
    """
    return create(
        db,
        user_id=assignee_id,
        kind=KIND_ASSIGNED,
        actor_user_id=actor.id,
        task_id=task.id,
        payload={"task": task.task, "actor_name": actor.name},
    )


def notify_mentioned(
    db: Session, *, user_id, task: Task, comment, actor: User, excerpt: str
) -> Optional[Notification]:
    """Someone was @mentioned in a comment.

    Deduped per COMMENT, not per task: editing a comment re-runs the mention
    sync, and without this a typo fix would notify everyone again.
    """
    return create(
        db,
        user_id=user_id,
        kind=KIND_MENTIONED,
        actor_user_id=actor.id,
        task_id=task.id,
        comment_id=comment.id,
        payload={"task": task.task, "actor_name": actor.name, "excerpt": excerpt[:280]},
        dedupe_key=f"mention:{comment.id}",
    )


def notify_due_soon(db: Session, task: Task, user_id) -> Optional[Notification]:
    """A card assigned to this person is due shortly.

    Deduped per task AND due date. Per task alone would mean a card whose
    deadline is pushed never reminds again; including the date lets a genuinely
    new deadline notify once more, while the timer re-running all day does not.
    """
    stamp = task.due_date.date().isoformat() if task.due_date else "none"
    return create(
        db,
        user_id=user_id,
        kind=KIND_DUE_SOON,
        actor_user_id=None,  # nobody did this; a clock did
        task_id=task.id,
        payload={"task": task.task, "due_date": stamp},
        dedupe_key=f"due:{task.id}:{stamp}",
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def unread_count(db: Session, user: User) -> int:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .count()
    )


def list_for(db: Session, user: User, *, limit: int = 30, unread_only: bool = False):
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    return q.order_by(Notification.created_at.desc()).limit(limit).all()


def mark_read(db: Session, user: User, notification_ids: Optional[list[int]] = None) -> int:
    """Mark some or all of this person's notifications read.

    Scoped to `user.id` on the UPDATE itself, not by fetching first and
    trusting the ids — otherwise passing someone else's notification id would
    silently clear their bell.
    """
    q = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.read_at.is_(None)
    )
    if notification_ids:
        q = q.filter(Notification.id.in_(notification_ids))
    n = q.update({Notification.read_at: _now()}, synchronize_session=False)
    db.commit()
    return n
