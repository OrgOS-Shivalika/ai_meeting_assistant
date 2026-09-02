"""Turning an owner's NAME into an account.

`tasks.owner_name` is free text the meeting analyzer wrote down — "Priya",
"the design team", "TBD", "Conversation Group". `tasks.assignee_user_id` is a
real foreign key, and `permissions.task_view_clause` already ORs it in, so
setting it GRANTS that person access to the task. That asymmetry is the whole
design of this module: a wrong guess does not mislabel a card, it hands
someone access to work they were never part of.

So the rule is exact or nothing. No fuzzy matching, no first-name-only, no
"closest Levenshtein". Those are fine for a search box and unacceptable for
something that decides who can read a task.

**What the data actually supports, measured 2026-09-02 rather than assumed:**
of 839 tasks carrying an owner name, 24 match an account exactly. The rest are
sentinels ("Conversation Group" alone accounts for 406), or real people who
have no account here. Participants are no help — 181 rows, 0 linked to users,
2 with an email at all.

The conclusion that follows: a backfill is not the answer, and building a
cleverer matcher will not change that. The answer is to resolve at WRITE time,
so tasks arrive assigned. This function is shared by both paths precisely so
they can never disagree about who "Priya" is.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import User
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

#: Owner labels that are never a person. Matched case-insensitively after
#: trimming. Mirrors the `is_unassigned` set the board cards already use, plus
#: the values this deployment's analyzer actually emits — `Conversation Group`
#: is 406 of 839 rows on its own, and `self_assigned_task` is a pipeline
#: artefact rather than anyone's name.
NON_PERSON_LABELS = frozenset({
    "", "tbd", "to be confirmed", "unassigned", "unknown", "n/a", "na",
    "-", "—", "null", "none", "unspecified", "team", "the team", "everyone",
    "all", "conversation group", "self_assigned_task", "group", "attendees",
    "participants",
})


def is_person_label(owner_name: Optional[str]) -> bool:
    """False for the sentinels above — cheap pre-filter before any query."""
    return (owner_name or "").strip().lower() not in NON_PERSON_LABELS


def resolve_assignee(
    db: Session, organization_id, owner_name: Optional[str]
) -> Optional[User]:
    """The account this owner label refers to, or None.

    Returns None — never a guess — when the label is a sentinel, matches
    nobody, or matches MORE than one person. The ambiguous case is the one
    worth spelling out: two people called "Sam" in an org means picking either
    is a coin flip that grants one of them access to something they may have
    no business seeing. Leaving it unassigned is recoverable; a wrong grant
    discovered later is not.

    Scoped to `organization_id` on every branch. A name is not unique across
    tenants, and resolving across them would be a cross-organization leak.
    """
    if not is_person_label(owner_name):
        return None

    label = owner_name.strip()

    # Email first: unique by construction where it matches at all, so it never
    # hits the ambiguity case below.
    matches = (
        db.query(User)
        .filter(
            User.organization_id == organization_id,
            func.lower(User.email) == label.lower(),
        )
        .all()
    )
    if not matches:
        matches = (
            db.query(User)
            .filter(
                User.organization_id == organization_id,
                func.lower(func.btrim(User.name)) == label.lower(),
            )
            .all()
        )

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        logger.info(
            "Assignee %r is ambiguous in org %s (%d accounts) — left unassigned",
            label, organization_id, len(matches),
        )
    return None


def task_organization_id(task) -> Optional[str]:
    """Which org a task belongs to.

    Tasks hang off a meeting OR a board, and manual board cards have no
    meeting at all — so neither parent alone is sufficient. Callers that
    resolve an assignee without this end up scoping to the wrong tenant, or
    to nothing.
    """
    meeting = getattr(task, "meeting", None)
    if meeting is not None and meeting.organization_id:
        return meeting.organization_id
    board = getattr(task, "board", None)
    if board is not None and board.organization_id:
        return board.organization_id
    return None
