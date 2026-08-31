"""Meeting / task / board authorization — the single source of truth.

Every access decision in the app resolves through this module. It exists
so the ~40 meeting-scoped endpoints can't drift apart: the security spec
requires list and detail APIs to agree, and the only durable way to get
that is to have one place that answers "what may this user see".

Three roles, on ``users.access_role`` (stored UPPERCASE):

``MEMBER``
    Implicit — nobody grants it. A user is a member of a meeting because
    they attended it, i.e. there is a ``participants`` row linking them
    to it. Sees those meetings, their tasks and their cards, plus any
    task assigned to them directly. A member may ALSO hold rows in
    ``category_admins``, which widen what they can see without letting
    them change any of it — see the grant/role split below.

``ADMIN``
    Category-level. Sees and manages everything in the categories granted
    to them via ``category_admins``. Their *view* scope is a union with
    their own attended meetings (an admin who joins a call outside their
    categories still sees that call) but their *write* scope is not —
    editing and deleting stay strictly inside managed categories.

``ORG_ADMIN``
    Everything in the organization.

**A grant says WHERE, the role says WHAT.** A ``category_admins`` row
names a category or team; it does not by itself confer the right to
change anything there. So the same row means "can read this category"
for a member and "can read and manage this category" for an admin, and
the view clauses below consult grants for every role while the manage
clauses consult them only for admins. The table name predates the split
and is now slightly narrow — read it as ``category_grants``.

That is why an org admin can scope a plain member: assigning them a
category or a team is not a promotion. Before this split every clause
gated the grant subqueries behind ``is_category_admin``, so a member's
grants were dead rows.

Two more conventions worth knowing before editing this file:

**Org scoping is still separate.** Nothing here replaces the existing
``organization_id`` filters. These clauses narrow *within* a tenant; the
caller is still responsible for the tenant boundary. Belt and braces —
a bug in one layer shouldn't hand over another org's data.

**404 across tenants, 403 within one.** Returning 403 for a meeting in
someone else's org would confirm the ID exists, which is exactly the
enumeration leak the existing code avoids. So: the row isn't in your org
→ 404, the row is in your org but you may not touch it → 403.

The scope helpers return either a SQLAlchemy clause or ``None``, where
``None`` means "no restriction" (org admin). Callers must treat ``None``
as unrestricted rather than as an empty filter::

    q = db.query(Meeting).filter(Meeting.organization_id == user.organization_id)
    clause = permissions.meeting_view_clause(db, user)
    if clause is not None:
        q = q.filter(clause)

They return clauses rather than lists of IDs on purpose: a busy org has
tens of thousands of meetings, and materializing the ID set into Python
to pass to ``IN`` would be both slow and racy.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import (
    Category,
    CategoryAdmin,
    KanbanBoard,
    Meeting,
    Participant,
    Task,
    Team,
    User,
)
from app.utils.admin_enums import AccessRole, ParticipantMatchSource


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

# Canonical definitions live in `app/utils/admin_enums.py`. These aliases
# are kept so the existing call sites in this module and its callers keep
# reading naturally — `AccessRole` is a str enum, so they are the plain
# strings they always were.
ROLE_MEMBER = AccessRole.MEMBER.value
ROLE_ADMIN = AccessRole.ADMIN.value
ROLE_ORG_ADMIN = AccessRole.ORG_ADMIN.value

VALID_ROLES = AccessRole.values()

# Which `participants.match_source` values are allowed to grant access.
#
# `participants.email` is derived by a fuzzy name-token heuristic in
# `MeetingPipeline.save_participants` — it matches a Recall.ai speaker
# name against any calendar attendee whose display name shares a token
# longer than two characters. That is a sensible bias for rendering an
# avatar and a terrible one for authorization: two colleagues named
# "Chris" are enough to hand one of them the other's meeting. So a link
# only counts when we know how it was made.
#
#   'calendar_exact' — exact email or exact full displayName match
#                      against the Google Calendar attendee list
#   'manual'         — an admin added this participant deliberately
#
# 'heuristic' and 'legacy' links are kept (they're useful for display and
# for suggesting assignees) but confer nothing.
TRUSTED_MATCH_SOURCES = ParticipantMatchSource.trusted()


def access_role(user: User) -> str:
    """The user's effective access role.

    Unknown or NULL → ``member``, the least-privileged value. The column
    is NOT NULL in the schema, but this stays defensive: a user object
    built outside the ORM (a test stub, a partially-loaded row) must not
    accidentally read as an admin.
    """
    return AccessRole.coerce(getattr(user, "access_role", None)).value


def is_org_admin(user: User) -> bool:
    return access_role(user) == ROLE_ORG_ADMIN


def is_category_admin(user: User) -> bool:
    """True for ``admin`` only — org admins are handled by their own,
    broader branch everywhere, so lumping them in here would make the
    call sites ambiguous."""
    return access_role(user) == ROLE_ADMIN


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------


def _attended_meeting_ids(user: User):
    """Subquery: IDs of meetings this user attended.

    Restricted to trusted match sources — see ``TRUSTED_MATCH_SOURCES``.
    """
    return (
        select(Participant.meeting_id)
        .where(
            Participant.user_id == user.id,
            Participant.match_source.in_(TRUSTED_MATCH_SOURCES),
        )
        .scalar_subquery()
    )


def _managed_category_ids(user: User):
    """Subquery: categories this user administers *in full*.

    Only whole-category grants (``team_id IS NULL``). A team-scoped grant
    deliberately does NOT appear here — it would widen the admin's scope
    from one team to the entire category, which is the opposite of what
    picking a team means.
    """
    return (
        select(CategoryAdmin.category_id)
        .where(
            CategoryAdmin.user_id == user.id,
            CategoryAdmin.team_id.is_(None),
        )
        .scalar_subquery()
    )


def _managed_team_ids(user: User):
    """Subquery: teams this user administers individually."""
    return (
        select(CategoryAdmin.team_id)
        .where(
            CategoryAdmin.user_id == user.id,
            CategoryAdmin.team_id.isnot(None),
        )
        .scalar_subquery()
    )


def _reachable_category_ids(user: User):
    """Subquery: categories this user administers in full OR holds a team
    inside.

    Used for *navigating* — an admin granted one team still has to see the
    parent category to get to it. Not for deciding what they may manage;
    that's :func:`_managed_category_ids`.
    """
    return (
        select(CategoryAdmin.category_id)
        .where(CategoryAdmin.user_id == user.id)
        .scalar_subquery()
    )


def managed_category_ids(db: Session, user: User) -> Optional[list[int]]:
    """Materialized list of WHOLE-category grants, or ``None`` for an org
    admin (who manages all of them).

    Whole-category only, matching :func:`_managed_category_ids`. It used
    to return every row's ``category_id``, team-scoped grants included,
    which made a user holding one team look like they held the category:
    the frontend's ``managesCategory()`` is built on this list and drew
    manage controls that the server then refused. Team grants are
    reported separately by :func:`managed_team_ids`.

    Only for callers that genuinely need the values — ``/auth/me`` and
    the admin management UI. Query filters should use the clause helpers
    below instead of round-tripping IDs through Python.
    """
    if is_org_admin(user):
        return None
    rows = (
        db.query(CategoryAdmin.category_id)
        .filter(
            CategoryAdmin.user_id == user.id,
            CategoryAdmin.team_id.is_(None),
        )
        .all()
    )
    return [r[0] for r in rows]


# --------------------------------------------------------------------------
# Meetings
# --------------------------------------------------------------------------


def managed_team_ids(db: Session, user: User) -> Optional[list[int]]:
    """Materialized list of individually-granted team IDs, or ``None`` for
    an org admin. Mirrors :func:`managed_category_ids`."""
    if is_org_admin(user):
        return None
    rows = (
        db.query(CategoryAdmin.team_id)
        .filter(
            CategoryAdmin.user_id == user.id,
            CategoryAdmin.team_id.isnot(None),
        )
        .all()
    )
    return [r[0] for r in rows]


def meeting_view_clause(db: Session, user: User) -> Optional[ColumnElement]:
    """Restrict ``Meeting`` rows to what ``user`` may see. ``None`` =
    unrestricted.

    Note what falls out for uncategorized meetings (``category_id IS
    NULL``): ``NULL IN (...)`` is never true, so they're visible to their
    attendees and to org admins, but not to category admins. That's
    deliberate — there's no category from which an admin could derive a
    right to them.
    """
    if is_org_admin(user):
        return None

    # Union, not replacement: someone who personally sat in a call
    # outside their granted categories still sees that call. Team grants
    # add a third, narrower path — a meeting filed under a granted team
    # even when the category as a whole isn't theirs.
    #
    # No role branch. Grants widen the view for members too, and a member
    # who holds none contributes two `IN (empty set)` arms, which is
    # exactly the attendance-only clause they had before.
    return or_(
        Meeting.id.in_(_attended_meeting_ids(user)),
        Meeting.category_id.in_(_managed_category_ids(user)),
        Meeting.team_id.in_(_managed_team_ids(user)),
    )


def meeting_manage_clause(db: Session, user: User) -> Optional[ColumnElement]:
    """Restrict ``Meeting`` rows to what ``user`` may create/edit/delete.

    Deliberately narrower than :func:`meeting_view_clause`: an admin's
    write rights come from the category grant only. Merely having
    attended a meeting never confers edit rights on it — otherwise every
    member could rename any call they joined.
    """
    if is_org_admin(user):
        return None
    if is_category_admin(user):
        return or_(
            Meeting.category_id.in_(_managed_category_ids(user)),
            Meeting.team_id.in_(_managed_team_ids(user)),
        )
    # Members never manage meetings.
    return _NEVER


# A clause that is always false. `False` on its own isn't a SQLAlchemy
# expression, and `and_()` with no arguments renders as TRUE — which
# would fail open. This is the explicit deny.
_NEVER = and_(Meeting.id.is_(None), Meeting.id.isnot(None))


def get_viewable_meeting(db: Session, user: User, meeting_id: int) -> Meeting:
    """Fetch a meeting the user is allowed to view, or raise.

    404 when the meeting doesn't exist or belongs to another org; 403
    when it's in this org but out of the caller's scope.
    """
    meeting = (
        db.query(Meeting)
        .filter(
            Meeting.id == meeting_id,
            Meeting.organization_id == user.organization_id,
        )
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    clause = meeting_view_clause(db, user)
    if clause is not None:
        permitted = (
            db.query(Meeting.id).filter(Meeting.id == meeting.id, clause).first()
        )
        if not permitted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this meeting.",
            )
    return meeting


def get_manageable_meeting(db: Session, user: User, meeting_id: int) -> Meeting:
    """Same as :func:`get_viewable_meeting` for write operations."""
    meeting = (
        db.query(Meeting)
        .filter(
            Meeting.id == meeting_id,
            Meeting.organization_id == user.organization_id,
        )
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    clause = meeting_manage_clause(db, user)
    if clause is not None:
        permitted = (
            db.query(Meeting.id).filter(Meeting.id == meeting.id, clause).first()
        )
        if not permitted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to modify this meeting.",
            )
    return meeting


def category_view_clause(db: Session, user: User) -> Optional[ColumnElement]:
    """Restrict ``Category`` rows to those the user may see.

    A category is visible when it is granted to them, or when they
    attended at least one meeting filed under it. Without this, the
    categories list leaks the shape of the whole organization — every
    department name, every client name — to anyone with a login, which
    also makes an admin's category grant look meaningless in the UI.
    """
    if is_org_admin(user):
        return None

    attended_here = Category.id.in_(
        select(Meeting.category_id)
        .where(
            Meeting.id.in_(_attended_meeting_ids(user)),
            Meeting.category_id.isnot(None),
        )
        .scalar_subquery()
    )

    # `_reachable_*`, not `_managed_*`: someone granted a single team must
    # still see the parent category to navigate into it. Applies to
    # members as well as admins — a member scoped to one team needs the
    # category header to find it.
    return or_(attended_here, Category.id.in_(_reachable_category_ids(user)))


def category_manage_clause(db: Session, user: User) -> Optional[ColumnElement]:
    """Restrict ``Category`` rows the user may rename or reconfigure.

    Grants only — attending a meeting in a category never confers the
    right to edit the category itself.
    """
    if is_org_admin(user):
        return None
    if is_category_admin(user):
        return Category.id.in_(_managed_category_ids(user))
    return _NEVER_CATEGORY


_NEVER_CATEGORY = and_(Category.id.is_(None), Category.id.isnot(None))


def team_view_clause(db: Session, user: User) -> Optional[ColumnElement]:
    """Restrict ``Team`` rows to those the user may see. ``None`` =
    unrestricted.

    Reaching a category does NOT mean reaching every team in it. A grant
    on one team makes that team visible and its siblings not, which is
    the whole point of picking a team instead of the category — without
    this, the category list still named every team in the organization's
    structure and a narrow grant looked no different from a broad one.

    Three ways in, mirroring the category rules one level down:
    a whole-category grant (which covers all of its teams), a grant on
    this specific team, or having attended a meeting filed under it.
    """
    if is_org_admin(user):
        return None
    return or_(
        Team.category_id.in_(_managed_category_ids(user)),
        Team.id.in_(_managed_team_ids(user)),
        Team.id.in_(
            select(Meeting.team_id)
            .where(
                Meeting.id.in_(_attended_meeting_ids(user)),
                Meeting.team_id.isnot(None),
            )
            .scalar_subquery()
        ),
    )


def require_team_access(
    db: Session, user: User, team: Team, *, manage: bool = False
) -> None:
    """Guard for endpoints addressing one team directly.

    Deliberately narrower than ``require_category_access`` on the same
    team's category: that helper answers "may you reach this category at
    all", which any grant inside it satisfies. Used for a team it would
    let someone holding team A read team B — different team, same parent.
    """
    if is_org_admin(user):
        return

    if manage and not is_category_admin(user):
        # Members manage no teams, whatever they are scoped to.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires an admin role.",
        )

    # A whole-category grant covers every team inside it.
    whole_category = (
        db.query(CategoryAdmin.id)
        .filter(
            CategoryAdmin.user_id == user.id,
            CategoryAdmin.category_id == team.category_id,
            CategoryAdmin.team_id.is_(None),
        )
        .first()
    )
    if whole_category:
        return

    this_team = (
        db.query(CategoryAdmin.id)
        .filter(
            CategoryAdmin.user_id == user.id,
            CategoryAdmin.team_id == team.id,
        )
        .first()
    )
    if this_team:
        return

    if not manage:
        attended_here = (
            db.query(Meeting.id)
            .filter(
                Meeting.team_id == team.id,
                Meeting.id.in_(_attended_meeting_ids(user)),
            )
            .first()
        )
        if attended_here:
            return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "You do not manage this team."
            if manage
            else "You do not have access to this team."
        ),
    )


def require_category_access(
    db: Session,
    user: User,
    category_id: Optional[int],
    *,
    manage: bool = False,
    team_id: Optional[int] = None,
) -> None:
    """Guard for endpoints that take a category directly — creating a
    meeting in it, uploading a document to it, listing its teams.

    ``category_id=None`` is allowed: an uncategorized meeting is a valid
    thing for an org admin or a member to work with. Members can't manage
    categories at all, so ``manage=True`` denies them outright.
    """
    if category_id is None:
        if manage and not is_org_admin(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an organization admin can manage uncategorized meetings.",
            )
        return

    category = (
        db.query(Category)
        .filter(
            Category.id == category_id,
            Category.organization_id == user.organization_id,
        )
        .first()
    )
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    if is_org_admin(user):
        return

    # A whole-category grant satisfies both read and manage.
    whole_category = (
        db.query(CategoryAdmin.id)
        .filter(
            CategoryAdmin.category_id == category_id,
            CategoryAdmin.user_id == user.id,
            CategoryAdmin.team_id.is_(None),
        )
        .first()
    )
    if whole_category:
        return

    # A team-scoped grant satisfies manage only for THAT team. Callers
    # that are acting on a specific team pass it in; without it a
    # team-scoped admin has no manage right over the category at large.
    if team_id is not None:
        team_grant = (
            db.query(CategoryAdmin.id)
            .filter(
                CategoryAdmin.category_id == category_id,
                CategoryAdmin.user_id == user.id,
                CategoryAdmin.team_id == team_id,
            )
            .first()
        )
        if team_grant:
            return

    # Reading the category itself is enough with any grant inside it —
    # an admin scoped to one team still has to see the parent to reach it.
    if not manage:
        any_grant = (
            db.query(CategoryAdmin.id)
            .filter(
                CategoryAdmin.category_id == category_id,
                CategoryAdmin.user_id == user.id,
            )
            .first()
        )
        if any_grant:
            return

    if manage:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not manage this category.",
        )

    # Read access without a grant: allowed only if they attended at least
    # one meeting in this category, which is what makes the category
    # visible to them in the first place.
    attended_here = (
        db.query(Meeting.id)
        .filter(
            Meeting.category_id == category_id,
            Meeting.id.in_(_attended_meeting_ids(user)),
        )
        .first()
    )
    if not attended_here:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this category.",
        )


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------


def task_view_clause(db: Session, user: User) -> Optional[ColumnElement]:
    """Restrict ``Task`` rows to what ``user`` may see.

    Assumes the query joins (or outer-joins) ``Meeting``. Tasks can have
    ``meeting_id IS NULL`` — manual Kanban cards — so the join must be an
    OUTER join or those cards vanish for everyone. A meeting-less card is
    visible to a member only when it's assigned to them.
    """
    if is_org_admin(user):
        return None

    return or_(
        Task.assignee_user_id == user.id,
        Task.meeting_id.in_(_attended_meeting_ids(user)),
        # Grants, for every role — same reasoning as
        # `meeting_view_clause`. A task is visible when its meeting is.
        Task.meeting_id.in_(
            select(Meeting.id)
            .where(
                or_(
                    Meeting.category_id.in_(_managed_category_ids(user)),
                    Meeting.team_id.in_(_managed_team_ids(user)),
                )
            )
            .scalar_subquery()
        ),
    )


def task_manage_clause(db: Session, user: User) -> Optional[ColumnElement]:
    """Restrict ``Task`` rows to what ``user`` may edit or delete.

    Members may update only tasks assigned to them. Note this is
    *narrower* than their view scope — a member sees every task from a
    meeting they attended but can only act on their own.
    """
    if is_org_admin(user):
        return None
    if is_category_admin(user):
        return Task.meeting_id.in_(
            select(Meeting.id)
            .where(
                or_(
                    Meeting.category_id.in_(_managed_category_ids(user)),
                    Meeting.team_id.in_(_managed_team_ids(user)),
                )
            )
            .scalar_subquery()
        )
    return Task.assignee_user_id == user.id


def get_viewable_task(db: Session, user: User, task_id: int) -> Task:
    """Fetch a task the user may view, or raise 404/403.

    The org check has to consider both parents: a task hangs off a
    meeting, off a board, or (transiently) off neither.
    """
    task = _task_in_org(db, user, task_id)
    clause = task_view_clause(db, user)
    if clause is not None:
        permitted = db.query(Task.id).filter(Task.id == task.id, clause).first()
        if not permitted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this task.",
            )
    return task


def get_manageable_task(db: Session, user: User, task_id: int) -> Task:
    """Same as :func:`get_viewable_task` for writes."""
    task = _task_in_org(db, user, task_id)
    clause = task_manage_clause(db, user)
    if clause is not None:
        permitted = db.query(Task.id).filter(Task.id == task.id, clause).first()
        if not permitted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to modify this task.",
            )
    return task


def _task_in_org(db: Session, user: User, task_id: int) -> Task:
    """Tenant check for a task. Mirrors the dual-parent logic already in
    ``meeting_service.update_task`` — a Kanban card created by hand has
    no meeting, so the org must come from its board instead."""
    task = (
        db.query(Task)
        .outerjoin(Meeting, Task.meeting_id == Meeting.id)
        .outerjoin(KanbanBoard, Task.board_id == KanbanBoard.id)
        .filter(
            Task.id == task_id,
            or_(
                Meeting.organization_id == user.organization_id,
                KanbanBoard.organization_id == user.organization_id,
            ),
        )
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# --------------------------------------------------------------------------
# Boards
# --------------------------------------------------------------------------
#
# Boards are org/category/team-scoped containers, never per-meeting, so
# "boards for meetings I attended" can't be answered at the board level.
# It's answered at the CARD level: a board is visible when it holds at
# least one card you may see, and when you open it you get only those
# cards. Same board, different contents per viewer.


def _viewable_category_ids(user: User):
    """Subqueries for the categories this user may VIEW.

    Deliberately mirrors :func:`category_view_clause` arm for arm — attended
    a meeting in it, or holds ANY grant inside it (``_reachable_*``, so a
    team-scoped grant counts: you must see the parent to reach the team).

    Returned as a tuple to be OR'd rather than UNION'd, so each stays a plain
    ``IN`` the planner can index. Distinct from
    :func:`visible_category_ids_subqueries`, which is narrower on purpose
    (whole-category grants only) because it gates DOCUMENT retrieval.
    """
    attended = (
        select(Meeting.category_id)
        .where(
            Meeting.id.in_(_attended_meeting_ids(user)),
            Meeting.category_id.isnot(None),
        )
        .scalar_subquery()
    )
    return attended, _reachable_category_ids(user)


def _viewable_team_ids(user: User):
    """Subqueries for the teams this user may VIEW. Mirrors
    :func:`team_view_clause`: a whole-category grant covers every team in it,
    a team grant covers that team, and attendance covers a team you sat in."""
    under_managed = (
        select(Team.id)
        .where(Team.category_id.in_(_managed_category_ids(user)))
        .scalar_subquery()
    )
    attended = (
        select(Meeting.team_id)
        .where(
            Meeting.id.in_(_attended_meeting_ids(user)),
            Meeting.team_id.isnot(None),
        )
        .scalar_subquery()
    )
    return under_managed, _managed_team_ids(user), attended


def board_view_clause(db: Session, user: User) -> Optional[ColumnElement]:
    """Restrict ``KanbanBoard`` rows to boards the user may open.

    Visibility follows the SCOPE, not the contents. A board scoped to a
    category you can see is yours to open even when it is empty — otherwise a
    freshly-created board is invisible to exactly the people it was made for,
    and stays invisible until somebody else's card happens to land on it.

    Four ways in, and a board needs only one:

    1. it holds at least one card you may see;
    2. it is scoped to a category you may view;
    3. it is scoped to a team you may view;
    4. a category or team you may view ROUTES its tasks to it
       (``default_board_id``) — that board is where your meetings' work lands,
       so you have to be able to open it. This arm is what makes an org-wide
       board reachable when a category points at one.

    Arms 2 and 3 used to consult ``_managed_*`` — whole-category grants only —
    which was strictly narrower than being able to see the category itself. A
    member who attended a meeting in a category, or an admin holding just one
    team inside it, could open the category and find none of its boards. They
    now use the same rule as :func:`category_view_clause` /
    :func:`team_view_clause`, so "can see the category" and "can see the
    category's boards" cannot drift apart.

    What is deliberately NOT here: an ORG-scoped board is still not visible
    from its scope alone. Org-wide means unbounded, so it is reachable only
    through arm 1 or arm 4 — a card you may see, or a category of yours
    pointing at it. And none of this grants WRITE access:
    :func:`board_manage_clause` is unchanged and still admin-only, so seeing
    a board never implies renaming or deleting it.

    Contents stay filtered independently. Opening a board shows only the cards
    :func:`task_view_clause` allows, so a visible board is not a visible
    backlog — the same board legitimately shows different cards to different
    people.
    """
    if is_org_admin(user):
        return None

    # `.correlate(KanbanBoard)` is load-bearing, not a hint. Without it
    # SQLAlchemy emits `FROM tasks, kanban_boards` inside the EXISTS —
    # an uncorrelated cross join that is true whenever ANY board in the
    # table holds a visible card, i.e. it makes every board visible to
    # everyone. Fails open, and silently.
    holds_a_visible_card = exists(
        select(Task.id)
        .where(Task.board_id == KanbanBoard.id)
        .where(task_view_clause(db, user))
        .correlate(KanbanBoard)
    )

    cat_parts = _viewable_category_ids(user)
    team_parts = _viewable_team_ids(user)

    # Arm 4 — the board a scope routes its tasks to. `isnot(None)` matters:
    # without it the subquery yields NULLs and `id IN (NULL, ...)` is never
    # true, which would quietly make this arm dead rather than wrong.
    pointed_at_by_category = KanbanBoard.id.in_(
        select(Category.default_board_id)
        .where(
            Category.default_board_id.isnot(None),
            or_(*[Category.id.in_(p) for p in cat_parts]),
        )
        .scalar_subquery()
    )
    pointed_at_by_team = KanbanBoard.id.in_(
        select(Team.default_board_id)
        .where(
            Team.default_board_id.isnot(None),
            or_(*[Team.id.in_(p) for p in team_parts]),
        )
        .scalar_subquery()
    )

    return or_(
        holds_a_visible_card,
        and_(
            KanbanBoard.scope_type == "category",
            or_(*[KanbanBoard.scope_id.in_(p) for p in cat_parts]),
        ),
        and_(
            KanbanBoard.scope_type == "team",
            or_(*[KanbanBoard.scope_id.in_(p) for p in team_parts]),
        ),
        pointed_at_by_category,
        pointed_at_by_team,
    )


def board_manage_clause(db: Session, user: User) -> Optional[ColumnElement]:
    """Restrict ``KanbanBoard`` rows the user may create into, rename,
    reconfigure or delete. Members manage no boards."""
    if is_org_admin(user):
        return None
    if is_category_admin(user):
        managed = _managed_category_ids(user)
        teams_under_managed = (
            select(Team.id).where(Team.category_id.in_(managed)).scalar_subquery()
        )
        return or_(
            and_(
                KanbanBoard.scope_type == "category",
                KanbanBoard.scope_id.in_(managed),
            ),
            and_(
                KanbanBoard.scope_type == "team",
                or_(
                    KanbanBoard.scope_id.in_(teams_under_managed),
                    KanbanBoard.scope_id.in_(_managed_team_ids(user)),
                ),
            ),
        )
    return _NEVER_BOARD


_NEVER_BOARD = and_(KanbanBoard.id.is_(None), KanbanBoard.id.isnot(None))


def get_viewable_board(db: Session, user: User, board_id: int) -> KanbanBoard:
    board = _board_in_org(db, user, board_id)
    clause = board_view_clause(db, user)
    if clause is not None:
        permitted = (
            db.query(KanbanBoard.id)
            .filter(KanbanBoard.id == board.id, clause)
            .first()
        )
        if not permitted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this board.",
            )
    return board


def get_manageable_board(db: Session, user: User, board_id: int) -> KanbanBoard:
    board = _board_in_org(db, user, board_id)
    clause = board_manage_clause(db, user)
    if clause is not None:
        permitted = (
            db.query(KanbanBoard.id)
            .filter(KanbanBoard.id == board.id, clause)
            .first()
        )
        if not permitted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to modify this board.",
            )
    return board


def _board_in_org(db: Session, user: User, board_id: int) -> KanbanBoard:
    board = (
        db.query(KanbanBoard)
        .filter(
            KanbanBoard.id == board_id,
            KanbanBoard.organization_id == user.organization_id,
        )
        .first()
    )
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


# --------------------------------------------------------------------------
# AI retrieval (RAG / graph / semantic search)
# --------------------------------------------------------------------------
#
# The most dangerous surface in the app, and the one the written spec
# never mentions. Every other endpoint hands back a row the user asked
# for by ID; retrieval hands back verbatim sentences from whatever the
# embedding space says is relevant. Filtering meetings but not retrieval
# means a member asks "what was decided about the restructure?" and gets
# the exec meeting read back to them, correctly cited.
#
# So the filter has to live in the SQL that selects chunks, not in a
# post-hoc pass over the results — a chunk that reaches the reranker has
# already been read.


def visible_meeting_ids_subquery(db: Session, user: User):
    """Subquery of meeting IDs the user may see, or ``None`` if
    unrestricted. Composable into any query with a ``meeting_id``."""
    clause = meeting_view_clause(db, user)
    if clause is None:
        return None
    return select(Meeting.id).where(clause).scalar_subquery()


def visible_category_ids_subqueries(db: Session, user: User):
    """The category IDs a user can reach, as a list of subqueries to be
    OR'd together, or ``None`` if unrestricted.

    Two sources, kept separate rather than UNION'd so each stays a plain
    ``IN`` the planner can use an index for: categories granted to them,
    and categories of meetings they attended.
    """
    if is_org_admin(user):
        return None
    return [
        select(Meeting.category_id)
        .where(
            Meeting.id.in_(_attended_meeting_ids(user)),
            Meeting.category_id.isnot(None),
        )
        .scalar_subquery(),
        # Whole-category grants, for every role. Team-only grants are
        # deliberately absent — they don't make the whole category
        # readable; `document_chunk_clause` adds them at the team level.
        _managed_category_ids(user),
    ]


def meeting_chunk_clause(db: Session, user: User, chunk_model) -> Optional[ColumnElement]:
    """Restrict a meeting-chunk-shaped model (anything with
    ``meeting_id``) to chunks from meetings the user may see."""
    subq = visible_meeting_ids_subquery(db, user)
    if subq is None:
        return None
    return chunk_model.meeting_id.in_(subq)


def document_chunk_clause(db: Session, user: User, chunk_model) -> Optional[ColumnElement]:
    """Restrict a document-chunk-shaped model (anything with
    ``category_id`` and ``team_id``) to documents the user may see.

    Knowledge documents are attached to a category or a team, never to a
    meeting, so they inherit category reachability. A chunk with neither
    set is org-wide and is deliberately withheld from non-org-admins:
    unscoped means unbounded, and there's no evidence the caller should
    see it.
    """
    parts = visible_category_ids_subqueries(db, user)
    if parts is None:
        return None
    visible_teams = [
        select(Team.id).where(Team.category_id.in_(p)).scalar_subquery()
        for p in parts
    ]
    return or_(
        *[chunk_model.category_id.in_(p) for p in parts],
        *[chunk_model.team_id.in_(t) for t in visible_teams],
        # A team-only grant reaches that team's documents and no further.
        # Without this arm the grant would be invisible here, because
        # `visible_category_ids_subqueries` reports whole categories only.
        chunk_model.team_id.in_(_managed_team_ids(user)),
    )


# --------------------------------------------------------------------------
# Role guards
# --------------------------------------------------------------------------


def require_org_admin_role(user: User) -> None:
    """For organization-wide management — provisioning admins, granting
    category rights."""
    if not is_org_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires the organization admin role.",
        )


def require_admin_role(user: User) -> None:
    """For anything an admin or an org admin may do, and a member may
    not."""
    if access_role(user) not in (ROLE_ADMIN, ROLE_ORG_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires an admin role.",
        )


# --------------------------------------------------------------------------
# Delegated administration
# --------------------------------------------------------------------------
#
# A category admin may run the Members page for their own categories and
# teams. Everything in this section answers one question: is the thing
# this actor is about to do confined to what they themselves hold?
#
# The rule, uniformly: an actor may set any role BELOW org admin, on any
# target that is not itself an org admin, with grants confined to their
# own scope. Org admins skip all of it.


def grant_scope(db: Session, user: User) -> Optional[tuple[set[int], set[int]]]:
    """``(whole_category_ids, team_ids)`` this user holds, or ``None``
    for an org admin (who holds everything).

    Materialized rather than a subquery because the callers are all
    membership tests against small sets, and the error messages need the
    actual IDs to be useful.
    """
    if is_org_admin(user):
        return None
    rows = (
        db.query(CategoryAdmin.category_id, CategoryAdmin.team_id)
        .filter(CategoryAdmin.user_id == user.id)
        .all()
    )
    categories = {cid for cid, tid in rows if tid is None}
    teams = {tid for _, tid in rows if tid is not None}
    return categories, teams


def assert_grants_within_scope(
    db: Session,
    actor: User,
    *,
    category_ids: list[int],
    team_ids: list[int],
) -> None:
    """Refuse to hand out access the actor does not hold.

    Without this a category admin could grant themselves — or anyone —
    any category in the organization, which turns delegated
    administration into full administration in one request.

    A team inside a wholly-granted category is allowed: holding the
    category means holding its teams. The reverse is not — holding one
    team confers nothing over the category.
    """
    scope = grant_scope(db, actor)
    if scope is None:
        return
    held_categories, held_teams = scope

    stray_categories = [c for c in category_ids if c not in held_categories]
    if stray_categories:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You can only grant categories you manage. "
                f"Not yours: {sorted(stray_categories)}"
            ),
        )

    if not team_ids:
        return
    # One query for the parents rather than per-team lookups; the picker
    # can submit a dozen teams at once.
    parents = dict(
        db.query(Team.id, Team.category_id).filter(Team.id.in_(team_ids)).all()
    )
    stray_teams = [
        t
        for t in team_ids
        if t not in held_teams and parents.get(t) not in held_categories
    ]
    if stray_teams:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You can only grant teams you manage. "
                f"Not yours: {sorted(stray_teams)}"
            ),
        )


def _drop_org_admins(db: Session, ids: set[UUID]) -> set[UUID]:
    """Remove every org admin from a visibility set.

    An org admin's row is never shown to a category admin or a member.
    Two reasons. Their access comes from the role and not from any grant,
    so there is nothing about it a delegated admin could act on — the
    write guards in ``admin_service`` already refuse. And the Members page
    is where names, email addresses, attendance counts and grant scope are
    exposed, which is precisely the detail an org admin should not be
    broadcasting to everyone they have delegated a category to.

    Safe to apply to the actor's own id: this is only reached for actors
    who are NOT org admins, because :func:`admin_visible_user_ids` returns
    ``None`` (unrestricted) for one long before here.
    """
    if not ids:
        return ids
    hidden = {
        r[0]
        for r in db.query(User.id)
        .filter(
            User.id.in_(sorted(ids)),
            User.access_role == ROLE_ORG_ADMIN,
        )
        .all()
    }
    return ids - hidden


def admin_visible_user_ids(db: Session, actor: User) -> Optional[set[UUID]]:
    """Users a category admin may see on the Members page, or ``None``
    for an org admin (everyone).

    Two ways to be in scope, mirroring the meeting rules: the person
    holds a grant inside the actor's scope, or they attended a meeting
    filed under it. The actor is always included — a page that omits the
    person reading it looks broken. Org admins are then removed, however
    they qualified: see :func:`_drop_org_admins`.

    Materialized because the Members page renders a whole org at once and
    the result feeds a single `IN`. An org with enough users for this to
    matter has an org admin doing the managing anyway.
    """
    scope = grant_scope(db, actor)
    if scope is None:
        return None
    held_categories, held_teams = scope

    ids: set[UUID] = {actor.id}

    # One exit, so the org-admin filter cannot be bypassed by an early
    # return added later.
    if held_categories or held_teams:
        # Teams inside a wholly-held category count as held.
        if held_categories:
            rows = (
                db.query(Team.id)
                .filter(Team.category_id.in_(sorted(held_categories)))
                .all()
            )
            held_teams = held_teams | {r[0] for r in rows}

        # Sorted lists rather than sets: `in_()` tolerates a set, but a
        # stable parameter order keeps the emitted SQL identical between
        # calls, which is what lets Postgres reuse the plan.
        cats = sorted(held_categories)
        teams = sorted(held_teams)

        grant_holders = db.query(CategoryAdmin.user_id).filter(
            or_(
                and_(
                    CategoryAdmin.category_id.in_(cats),
                    CategoryAdmin.team_id.is_(None),
                ),
                CategoryAdmin.team_id.in_(teams),
            )
        )
        ids.update(r[0] for r in grant_holders.all())

        attendees = (
            db.query(Participant.user_id)
            .join(Meeting, Participant.meeting_id == Meeting.id)
            .filter(
                Participant.user_id.isnot(None),
                Participant.match_source.in_(TRUSTED_MATCH_SOURCES),
                or_(
                    Meeting.category_id.in_(cats),
                    Meeting.team_id.in_(teams),
                ),
            )
        )
        ids.update(r[0] for r in attendees.all())

    return _drop_org_admins(db, ids)
