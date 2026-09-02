"""@mentions inside task comments.

Storage is the comment `body` itself — no schema change. A mention is:

    @[Divyansh Bhardwaj](3f2a1b4c-...-uuid)

The display name is snapshotted INLINE, matching `TaskComment.author_name`,
which is snapshotted for the same reason: the comment must still read correctly
after the mentioned user is renamed or deleted. The uuid is the identity; the
name is only what gets drawn.

Two rules here are security, not formatting:

1. **A mention is validated against the AUTHOR'S ORGANIZATION.** Checking that
   the uuid merely *exists* would let a crafted body embed a user from another
   tenant, and the moment anything resolves that uuid to a name — rendering
   server-side, or a future notification — it discloses the existence and name
   of someone in another organization.

2. **The display name is rewritten from the database, never trusted.** The
   client supplies the whole body, so nothing stops `@[Chief Executive](uuid-of-
   an-intern)`. Rewriting keeps the snapshot benefit and removes the
   impersonation vector: the client's name is a hint, the uuid is the truth.

A mention confers NO access. It never has, and it must not start to — same rule
as `tasks.assignee_user_id` being admin-only precisely because assigning DOES
grant access (`permissions.STATUS_FIELDS`).
"""
from __future__ import annotations

import re
import uuid as _uuid
from typing import Iterable
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import User

# Display text is capped well under the column limit and may not contain `]`,
# which would end the group early and desynchronise the parse.
MENTION_RE = re.compile(r"@\[([^\]\n]{1,120})\]\(([0-9a-fA-F-]{36})\)")

# How many distinct people one comment may tag. Not a security limit — a guard
# against a paste turning into a hundred lookups, and against a comment that is
# nothing but mentions.
MAX_MENTIONS_PER_COMMENT = 20


def parse_mentions(body: str) -> list[tuple[str, str]]:
    """Every `(display_name, uuid_string)` in `body`, in order of appearance.

    Malformed uuids are not filtered here — `validate_and_normalize` rejects
    them, so that the caller gets one clear error instead of a mention being
    silently dropped.
    """
    return [(m.group(1), m.group(2)) for m in MENTION_RE.finditer(body or "")]


def strip_mentions(body: str) -> str:
    """`body` with mentions flattened to plain `@Name`.

    For anywhere the raw markup would leak into a human-facing string that has
    no renderer — chiefly the `body_preview` written into `task_activity`,
    which would otherwise show `@[Name](3f2a...)` in the activity feed.
    """
    return MENTION_RE.sub(lambda m: "@" + m.group(1), body or "")


def mentioned_user_ids(body: str) -> list[UUID]:
    """Distinct, well-formed mentioned user ids. Order-preserving.

    Convenience for a future notifier; nothing in the render-only path needs
    it. Silently skips unparseable uuids because callers of THIS function are
    reading already-validated bodies.
    """
    seen: set[UUID] = set()
    out: list[UUID] = []
    for _, raw in parse_mentions(body):
        try:
            parsed = _uuid.UUID(raw)
        except ValueError:
            continue
        if parsed not in seen:
            seen.add(parsed)
            out.append(parsed)
    return out


def validate_and_normalize(db: Session, body: str, *, organization_id) -> str:
    """Check every mention and rewrite its display name. Returns the new body.

    Raises 400 when a mention names somebody who is not a user of
    `organization_id` — including a user of another organization, which is
    reported identically to "no such user" so the response cannot be used to
    probe for accounts elsewhere.

    Rejecting rather than silently stripping is deliberate: a dropped mention
    looks to the author like it worked, and silent degradation is this
    codebase's characteristic failure.
    """
    found = parse_mentions(body)
    if not found:
        return body

    if len(found) > MAX_MENTIONS_PER_COMMENT:
        raise HTTPException(
            status_code=400,
            detail=f"A comment may mention at most {MAX_MENTIONS_PER_COMMENT} people.",
        )

    parsed: dict[str, UUID] = {}
    for _, raw in found:
        try:
            parsed[raw] = _uuid.UUID(raw)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="A mention refers to an invalid user.",
            )

    # ONE query for every mentioned id, scoped to the org. The org filter is
    # the tenant boundary for this feature — see the module docstring.
    rows = (
        db.query(User.id, User.name)
        .filter(
            User.id.in_(set(parsed.values())),
            User.organization_id == organization_id,
        )
        .all()
    )
    names: dict[UUID, str] = {r[0]: r[1] for r in rows}

    missing = [raw for raw, parsed_id in parsed.items() if parsed_id not in names]
    if missing:
        raise HTTPException(
            status_code=400,
            detail="A mention refers to someone who is not a member of this organization.",
        )

    def _rewrite(match: re.Match) -> str:
        real = names.get(_uuid.UUID(match.group(2)), match.group(1))
        # `]` would terminate the group and corrupt every later mention, so a
        # name containing one is neutralised rather than rejected — the user
        # did not choose their own display name here.
        return f"@[{real.replace(']', '')}]({match.group(2)})"

    return MENTION_RE.sub(_rewrite, body)


def annotate_viewers(db: Session, task_id: int, users: Iterable) -> dict:
    """`{user_id: can_view}` for one task — drives the picker's "no access" tag.

    One small query per candidate. Fine at this scale (the largest org in
    production has 10 users) and it keeps the answer coming from
    `task_view_clause` rather than from a second, drifting copy of the rules.

    ponytail: per-user query; batch it if an org ever reaches hundreds of
    members and this shows up in the drawer's load time.
    """
    from app.db.models import Task
    from app.services import permissions

    out: dict = {}
    for u in users:
        clause = permissions.task_view_clause(db, u)
        q = db.query(Task.id).filter(Task.id == task_id)
        if clause is not None:
            q = q.filter(clause)
        out[u.id] = q.first() is not None
    return out


# ---------------------------------------------------------------------------
# Read state — the unread dot on a card
# ---------------------------------------------------------------------------


def sync_comment_mentions(db: Session, comment, *, author_user_id=None) -> int:
    """Rewrite `comment_mentions` to match the comment's body. Returns rows added.

    Called on create AND on edit, because an edit can add or remove a mention.
    Surviving rows keep their `read_at` — re-marking an already-read mention as
    unread because somebody fixed a typo elsewhere in the comment would train
    people to ignore the dot.

    The author is never mentioned to themselves: a dot on your own comment is
    noise, and you have by definition already seen it.
    """
    from app.db.models import CommentMention

    wanted = set(mentioned_user_ids(comment.body or ""))
    if author_user_id is not None:
        wanted.discard(author_user_id)

    existing = {
        row.user_id: row
        for row in db.query(CommentMention).filter(
            CommentMention.comment_id == comment.id
        )
    }

    for user_id, row in existing.items():
        if user_id not in wanted:
            db.delete(row)

    added = 0
    for user_id in wanted:
        if user_id in existing:
            continue
        db.add(CommentMention(
            comment_id=comment.id,
            task_id=comment.task_id,
            user_id=user_id,
        ))
        added += 1
    db.flush()
    return added


def unread_task_ids(db: Session, user, task_ids) -> set:
    """Which of `task_ids` have an unread mention for `user`.

    One query for the whole board — the alternative is a lookup per card, and
    a board can hold a hundred. Empty input short-circuits so a board with no
    cards costs nothing.
    """
    from app.db.models import CommentMention

    ids = list(task_ids)
    if not ids:
        return set()
    rows = (
        db.query(CommentMention.task_id)
        .filter(
            CommentMention.user_id == user.id,
            CommentMention.task_id.in_(ids),
            CommentMention.read_at.is_(None),
        )
        .distinct()
        .all()
    )
    return {r[0] for r in rows}


def mark_task_mentions_read(db: Session, user, task_id: int) -> int:
    """Clear the dot for one card. Returns how many mentions were marked.

    Scoped to `user.id`, so this can never clear somebody else's dot — the
    endpoint takes only a task id, and without that filter any user could mark
    the whole org's mentions read.
    """
    from datetime import datetime, timezone

    from app.db.models import CommentMention

    n = (
        db.query(CommentMention)
        .filter(
            CommentMention.user_id == user.id,
            CommentMention.task_id == task_id,
            CommentMention.read_at.is_(None),
        )
        .update({"read_at": datetime.now(timezone.utc)}, synchronize_session=False)
    )
    db.commit()
    return n


def unread_summary(db: Session, user) -> dict:
    """This viewer's unread mentions, rolled up for the sidebar + board list.

    Returns `{count, task_ids, board_ids}`.

    Filtered through `task_view_clause`, unlike `unread_task_ids` — that one is
    handed ids from a board the caller already opened, so the check would be
    redundant there. Here the query starts from the mention rows, and a mention
    can legitimately land on a card the person cannot open (the picker lets you
    tag anyone in the org, and a mention grants nothing). Surfacing those would
    put a dot on a board they can never open to clear, and an indicator you
    cannot act on just decays into noise.
    """
    from app.db.models import CommentMention, Task
    from app.services import permissions

    q = (
        db.query(CommentMention.task_id, Task.board_id)
        .join(Task, Task.id == CommentMention.task_id)
        .filter(
            CommentMention.user_id == user.id,
            CommentMention.read_at.is_(None),
        )
    )
    clause = permissions.task_view_clause(db, user)
    if clause is not None:
        q = q.filter(clause)

    rows = q.distinct().all()
    return {
        "count": len(rows),
        "task_ids": sorted({t for t, _b in rows}),
        "board_ids": sorted({b for _t, b in rows if b is not None}),
    }
