"""Organization member + admin management.

Backs the Members page. Everything here is org-admin-only; the router
enforces that once, at the door, rather than per function.

The provisioning flow this implements: an org admin names someone, picks
the categories they should administer, and the server creates the
account with a generated password and the grants attached. Members are
never created this way — attendance already makes someone a member, so
the only accounts worth provisioning by hand are elevated ones.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Category, CategoryAdmin, Meeting, Participant, Team, User,
)
from app.schemas.admin_schema import (
    AdminCreateRequest,
    MemberCreateRequest,
    RoleUpdateRequest,
)
from app.services import permissions
from app.services import mail_service, mail_templates
from app.services.auth_service import hash_password, verify_password
from app.utils.admin_enums import AccessRole, ParticipantMatchSource
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# Long enough that it can't be guessed and awkward enough that nobody is
# tempted to keep it. `token_urlsafe(18)` is 24 characters of base64 —
# roughly 144 bits.
_TEMP_PASSWORD_BYTES = 18


def _generate_temporary_password() -> str:
    return secrets.token_urlsafe(_TEMP_PASSWORD_BYTES)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def _serialize_member(
    user: User,
    grants: list[CategoryAdmin],
    meeting_count: int,
) -> dict:
    """Shape one member for the Members page.

    `managed_categories` holds whole-category grants only; team-scoped
    grants go in `managed_teams` with their parent category attached. The
    UI needs the split to tick the right boxes — a team grant must not
    render as though the whole category were granted.
    """
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "access_role": permissions.access_role(user),
        "must_change_password": bool(user.must_change_password),
        "created_at": user.created_at,
        "managed_categories": [
            {"id": g.category.id, "name": g.category.name}
            for g in grants
            if g.team_id is None and g.category is not None
        ],
        "managed_teams": [
            {
                "id": g.team.id,
                "name": g.team.name,
                "category_id": g.category_id,
                "category_name": g.category.name if g.category else None,
            }
            for g in grants
            if g.team_id is not None and g.team is not None
        ],
        "meeting_count": meeting_count,
    }


def list_members(db: Session, actor: User) -> list[dict]:
    """People the actor may administer, with their grants and attendance
    counts.

    An org admin gets the whole organization. A category admin gets the
    people inside their categories and teams — anyone holding a grant
    there or who attended a meeting filed there, plus themselves.

    Three batched queries rather than per-user lookups — the Members
    page renders the whole list at once and an N+1 here is felt
    immediately.
    """
    query = db.query(User).filter(User.organization_id == actor.organization_id)
    visible = permissions.admin_visible_user_ids(db, actor)
    if visible is not None:
        # `sorted` for a stable parameter order — see the note in
        # `permissions.admin_visible_user_ids`.
        query = query.filter(User.id.in_(sorted(visible)))
    users = (
        query
        .order_by(User.created_at.asc().nullslast(), User.name.asc())
        .all()
    )
    if not users:
        return []

    user_ids = [u.id for u in users]

    grants: dict[UUID, list[CategoryAdmin]] = {uid: [] for uid in user_ids}
    grant_rows = (
        db.query(CategoryAdmin)
        .options(
            joinedload(CategoryAdmin.category),
            joinedload(CategoryAdmin.team),
        )
        .filter(CategoryAdmin.user_id.in_(user_ids))
        .all()
    )
    for row in grant_rows:
        grants[row.user_id].append(row)

    # Attendance counts. Only trusted links count, so this number matches
    # what the user can actually open rather than what we merely suspect
    # about them.
    counts = dict(
        db.query(Participant.user_id, func.count(func.distinct(Participant.meeting_id)))
        .filter(
            Participant.user_id.in_(user_ids),
            Participant.match_source.in_(permissions.TRUSTED_MATCH_SOURCES),
        )
        .group_by(Participant.user_id)
        .all()
    )

    return [
        _serialize_member(u, grants.get(u.id, []), counts.get(u.id, 0))
        for u in users
    ]


def get_member_for_actor(db: Session, actor: User, user_id: UUID) -> dict:
    """One member, gated on the actor's administrative scope.

    Separate from :func:`get_member`, which is the plain serializer used
    to build a response after a write that was already authorized.
    """
    target = _require_manageable_target(db, actor, user_id)
    return get_member(db, actor.organization_id, target.id)


def get_member(db: Session, org_id: UUID, user_id: UUID) -> dict:
    user = _require_org_user(db, org_id, user_id)
    grants = (
        db.query(CategoryAdmin)
        .options(
            joinedload(CategoryAdmin.category),
            joinedload(CategoryAdmin.team),
        )
        .filter(CategoryAdmin.user_id == user.id)
        .all()
    )
    count = (
        db.query(func.count(func.distinct(Participant.meeting_id)))
        .filter(
            Participant.user_id == user.id,
            Participant.match_source.in_(permissions.TRUSTED_MATCH_SOURCES),
        )
        .scalar()
        or 0
    )
    return _serialize_member(user, grants, count)


def _require_org_user(db: Session, org_id: UUID, user_id: UUID) -> User:
    user = (
        db.query(User)
        .filter(User.id == user_id, User.organization_id == org_id)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# --------------------------------------------------------------------------
# Delegated administration guards
# --------------------------------------------------------------------------
#
# A category admin runs this page for their own categories and teams. One
# rule covers every write here: they may set any role below org admin, on
# any target that is not itself an org admin, with grants confined to
# what they hold. `permissions.assert_grants_within_scope` enforces the
# grant half; the two guards below enforce the target and role halves.


def _require_manageable_target(db: Session, actor: User, user_id: UUID) -> User:
    """Load a user the actor is allowed to act on.

    404 outside the org, 403 inside it but outside the actor's scope —
    the same split the rest of the app uses.

    Org admins are off limits to a category admin even when in scope.
    Their access does not come from any grant, so there is nothing a
    category admin could meaningfully change about it, and allowing the
    attempt would only produce a confusing partial result.
    """
    target = _require_org_user(db, actor.organization_id, user_id)
    if permissions.is_org_admin(actor):
        return target

    visible = permissions.admin_visible_user_ids(db, actor)
    if visible is not None and target.id not in visible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="That person is not in a category you manage.",
        )
    if permissions.access_role(target) == permissions.ROLE_ORG_ADMIN:
        # Unreachable in practice — `admin_visible_user_ids` already drops
        # org admins, so the scope check above rejects them first. Kept as
        # the second layer, and worded IDENTICALLY to it on purpose: a
        # distinct message here would let a category admin walk user ids
        # and learn which one is the org admin, which is the very thing
        # the concealment exists to prevent.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="That person is not in a category you manage.",
        )
    return target


def _assert_can_set_role(actor: User, new_role: str) -> None:
    """A category admin may not mint an org admin.

    They may promote to ADMIN within their own scope — that is delegation
    and it is intended. ORG_ADMIN is not scoped to anything, so granting
    it would hand over the whole organization.
    """
    if permissions.is_org_admin(actor):
        return
    if new_role == permissions.ROLE_ORG_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an organization admin can grant the organization admin role.",
        )


def _out_of_scope_pairs(
    db: Session, actor: User, target: User
) -> set[tuple[int, Optional[int]]]:
    """The target's existing grants that ``actor`` cannot see.

    Preserved verbatim across an edit. The Members UI sends the full
    intended grant set, but a category admin's picker only ever offered
    them their own categories — so treating an omission as a revocation
    would let one admin silently strip another's unrelated access by
    saving a form they could not have filled in correctly.
    """
    scope = permissions.grant_scope(db, actor)
    if scope is None:
        return set()
    held_categories, held_teams = scope
    if held_categories:
        rows = (
            db.query(Team.id)
            .filter(Team.category_id.in_(sorted(held_categories)))
            .all()
        )
        held_teams = held_teams | {r[0] for r in rows}

    keep: set[tuple[int, Optional[int]]] = set()
    rows = db.query(CategoryAdmin).filter(CategoryAdmin.user_id == target.id).all()
    for row in rows:
        in_scope = (
            row.category_id in held_categories
            if row.team_id is None
            else row.team_id in held_teams
        )
        if not in_scope:
            keep.add((row.category_id, row.team_id))
    return keep


# --------------------------------------------------------------------------
# Provisioning
# --------------------------------------------------------------------------


def create_admin(
    db: Session, actor: User, payload: AdminCreateRequest
) -> tuple[dict, Optional[str], Optional[mail_service.SendResult]]:
    """Create an admin account in the actor's org and grant it
    categories.

    Returns ``(serialized_user, temporary_password)``. The password is
    returned only here and never stored in plaintext.

    Re-provisioning an existing account is allowed and does NOT reset
    their password: someone who already attended a meeting has an
    account, and promoting them shouldn't lock them out of it.
    """
    email = payload.email.strip().lower()
    categories = _resolve_categories(db, actor.organization_id, payload.category_ids)
    teams = _resolve_teams(db, actor.organization_id, payload.team_ids)

    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing is not None:
        if existing.organization_id != actor.organization_id:
            # Deliberately vague: confirming that this address has an
            # account in some other organization is not our disclosure
            # to make.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That email address is not available.",
            )
        # Promote in place.
        existing.access_role = AccessRole.ADMIN
        _replace_grants(db, existing, categories, granted_by=actor, teams=teams)
        db.commit()
        db.refresh(existing)
        logger.info(
            "Promoted existing user %s to admin over %d categories (by %s)",
            existing.email, len(categories), actor.email,
        )
        # Promotion reuses the existing account and leaves its password
        # alone, so there is no credential to email.
        return get_member(db, actor.organization_id, existing.id), None, None

    temporary_password = _generate_temporary_password()
    user = User(
        name=payload.name.strip(),
        email=email,
        password=hash_password(temporary_password),
        organization_id=actor.organization_id,
        access_role=AccessRole.ADMIN,
        # They can log in, and then must set their own password before
        # the API will do anything else for them.
        must_change_password=True,
        password_set_at=None,
    )
    db.add(user)
    db.flush()

    _replace_grants(db, user, categories, granted_by=actor, teams=teams)

    # Attendance is membership, so a person provisioned today should
    # inherit access to meetings they already sat in. Their participant
    # rows exist but were never linked to an account, because there
    # wasn't one to link to.
    linked = _link_existing_participation(db, user)

    db.commit()
    db.refresh(user)
    logger.info(
        "Provisioned admin %s over %d categories, linked %d prior meetings (by %s)",
        user.email, len(categories), linked, actor.email,
    )
    email_result = send_invite(db, user, temporary_password, invited_by=actor)
    return (
        get_member(db, actor.organization_id, user.id),
        temporary_password,
        email_result,
    )


def create_member(
    db: Session, actor: User, payload: MemberCreateRequest
) -> tuple[dict, str, int, mail_service.SendResult]:
    """Add a user to the actor's organization with an explicit role and a
    caller-chosen password.

    Returns ``(serialized_user, password, linked_meeting_count, email_result)``.

    Unlike :func:`create_admin` this refuses to reuse an existing account.
    Setting a password on a live account is a takeover of it, and the flow
    this backs shows that password to the creator — so an accidental email
    collision must fail loudly instead of silently handing someone else's
    account over. Changing an existing user's role goes through
    :func:`update_member`.

    Grants arrive with the request and are written in this transaction.
    They cannot be a follow-up call: the new account holds no grants and
    has attended nothing, so it is outside a category admin's visible set
    until the moment its first grant exists, and
    :func:`_require_manageable_target` would refuse the very request that
    was going to fix that.
    """
    email = payload.email.strip().lower()

    if payload.access_role not in permissions.VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"access_role must be one of {permissions.VALID_ROLES}",
        )
    # A category admin may create members and admins, not org admins.
    _assert_can_set_role(actor, payload.access_role)

    # Resolved and scope-checked BEFORE the account exists, so a grant the
    # actor doesn't hold fails without leaving an orphan account behind.
    categories = _resolve_categories(db, actor.organization_id, payload.category_ids)
    teams = _resolve_teams(db, actor.organization_id, payload.team_ids)
    permissions.assert_grants_within_scope(
        db,
        actor,
        category_ids=payload.category_ids,
        team_ids=payload.team_ids,
    )

    # A category admin creating someone with no scope at all would create
    # a person they cannot then see: no grant and no attendance puts the
    # new account outside their own visible set, so it would vanish from
    # the page that created it and only an org admin could recover it.
    if not permissions.is_org_admin(actor) and not categories and not teams:
        raise HTTPException(
            status_code=400,
            detail=(
                "Pick at least one category or team. Someone created "
                "outside the categories you manage would not be visible "
                "to you afterwards."
            ),
        )

    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing is not None:
        # Deliberately identical whether the clash is in this org or
        # another — "which organization owns this address" is not ours to
        # disclose.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email address is already registered.",
        )

    # `users.name` is NOT NULL and the form only collects three fields, so
    # fall back to the email local-part rather than rejecting the request.
    name = (payload.name or "").strip() or email.split("@", 1)[0]

    user = User(
        name=name,
        email=email,
        password=hash_password(payload.password),
        organization_id=actor.organization_id,
        access_role=payload.access_role,
        # The creator knows this password, so it can't stay the account's
        # real one. The auth dependency blocks everything except
        # /auth/me, /auth/change-password and /auth/logout until it's
        # replaced.
        must_change_password=True,
        password_set_at=None,
    )
    db.add(user)
    db.flush()

    if categories or teams:
        _replace_grants(db, user, categories, granted_by=actor, teams=teams)

    # Attendance is membership, so a new account inherits the meetings
    # this person already sat in before they had a login.
    linked = _link_existing_participation(db, user)

    db.commit()
    db.refresh(user)
    logger.info(
        "Created %s %s in org %s over %d categories + %d teams "
        "(linked %d prior meetings) by %s",
        payload.access_role, user.email, actor.organization_id,
        len(categories), len(teams), linked, actor.email,
    )

    # After the commit, never before: an invite for an account that failed
    # to save would send someone a password that doesn't work.
    email_result = send_invite(db, user, payload.password, invited_by=actor)

    return (
        get_member(db, actor.organization_id, user.id),
        payload.password,
        linked,
        email_result,
    )


def _link_existing_participation(db: Session, user: User) -> int:
    """Attach a new account to participant rows that already carry its
    email.

    Only rows whose email came from the exact calendar path are linked
    as trusted — a heuristic row keeps its provenance and stays
    non-granting. See ``permissions.TRUSTED_MATCH_SOURCES``.
    """
    rows = (
        db.query(Participant)
        .join(Meeting, Participant.meeting_id == Meeting.id)
        .filter(
            Meeting.organization_id == user.organization_id,
            Participant.user_id.is_(None),
            func.lower(Participant.email) == user.email.lower(),
        )
        .all()
    )
    for row in rows:
        row.user_id = user.id
        if row.match_source is None:
            # The pipeline clears provenance when it can't link a row, so
            # a NULL here means "we had an exact email but no account".
            # Now there's an account.
            row.match_source = ParticipantMatchSource.CALENDAR_EXACT.value
    return len(rows)


def update_member(
    db: Session, actor: User, user_id: UUID, payload: RoleUpdateRequest
) -> dict:
    """Change a user's role and/or replace their category grants.

    Note that assigning grants is NOT a promotion. A grant says where a
    person may look; their role says what they may do there. So a plain
    member can be scoped to a category or a team and stay a member —
    they gain read access to it and nothing else.
    """
    user = _require_manageable_target(db, actor, user_id)

    if payload.access_role is not None:
        if payload.access_role not in permissions.VALID_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"access_role must be one of {permissions.VALID_ROLES}",
            )
        _assert_can_set_role(actor, payload.access_role)
        if user.id == actor.id and payload.access_role != permissions.access_role(actor):
            # Self-demotion is how an organization ends up with nobody
            # who can administer it — and how a category admin locks
            # themselves out of the page they are standing on.
            raise HTTPException(
                status_code=400,
                detail="You cannot change your own role.",
            )
        _guard_last_org_admin(db, user, payload.access_role)
        user.access_role = payload.access_role

    if payload.category_ids is not None or payload.team_ids is not None:
        # Either field being present rewrites the whole grant set, so an
        # omitted field is read as "none of those" rather than "leave
        # alone" — otherwise a UI that only sends categories could never
        # clear a team grant.
        requested_categories = payload.category_ids or []
        requested_teams = payload.team_ids or []
        # Nobody may hand out access they do not hold themselves.
        permissions.assert_grants_within_scope(
            db, actor, category_ids=requested_categories, team_ids=requested_teams
        )
        categories = _resolve_categories(
            db, actor.organization_id, requested_categories
        )
        teams = _resolve_teams(db, actor.organization_id, requested_teams)
        _replace_grants(
            db,
            user,
            categories,
            granted_by=actor,
            teams=teams,
            # Grants the actor cannot see survive their edit.
            keep=_out_of_scope_pairs(db, actor, user),
        )

    db.commit()
    logger.info(
        "Updated member %s (role=%s, grants=%s) by %s",
        user.email, payload.access_role, payload.category_ids, actor.email,
    )
    return get_member(db, actor.organization_id, user.id)


def _guard_last_org_admin(db: Session, user: User, new_role: str) -> None:
    """Refuse a change that would leave the org with no org admin."""
    if user.access_role != permissions.ROLE_ORG_ADMIN:
        return
    if new_role == permissions.ROLE_ORG_ADMIN:
        return
    remaining = (
        db.query(func.count(User.id))
        .filter(
            User.organization_id == user.organization_id,
            User.access_role == permissions.ROLE_ORG_ADMIN,
            User.id != user.id,
        )
        .scalar()
        or 0
    )
    if remaining == 0:
        raise HTTPException(
            status_code=400,
            detail="This is the only organization admin. Promote someone else first.",
        )


def revoke_admin(db: Session, actor: User, user_id: UUID) -> dict:
    """Demote a user to plain member and drop every category grant.

    The account itself survives — they attended meetings, and deleting
    the user would orphan that history.
    """
    user = _require_manageable_target(db, actor, user_id)
    if user.id == actor.id:
        raise HTTPException(
            status_code=400, detail="You cannot revoke your own access."
        )
    _guard_last_org_admin(db, user, permissions.ROLE_MEMBER)
    user.access_role = permissions.ROLE_MEMBER
    # Grants outside the actor's own scope survive — a category admin
    # revoking someone's rights over *their* categories has no mandate
    # over categories they cannot see. For an org admin this set is
    # empty, so the demotion drops everything, as before.
    _replace_grants(
        db, user, [], granted_by=actor, keep=_out_of_scope_pairs(db, actor, user)
    )
    db.commit()
    logger.info("Revoked admin from %s by %s", user.email, actor.email)
    return get_member(db, actor.organization_id, user.id)


def delete_member(db: Session, actor: User, user_id: UUID) -> dict:
    """Remove an account from the organization for good.

    A hard delete, but NOT a bare ``db.delete(user)`` — the foreign keys
    into ``users`` are not uniformly safe and two of them have to be
    dealt with first:

    ``categories.user_id`` is NOT NULL with ``ON DELETE CASCADE``. Deleting
        whoever created a category would therefore delete the CATEGORY,
        and with it every team and document inside it, every
        ``category_admins`` grant pointing at it, and the filing of every
        meeting in it (``meetings.category_id`` is SET NULL) — which is
        also what drives access scope and agent routing. That column
        records who created the row and confers nothing, so it is
        reassigned to the actor rather than followed.

    ``meetings.user_id`` has no ``ON DELETE`` clause at all, so the delete
        would simply fail on a foreign-key violation. Nulled explicitly.
        The meeting itself is org-owned and survives.

    Everything else is already correct: their comments, task activity,
    uploads, audit rows and task assignments are SET NULL and survive
    authorless, while their category grants and their own RAG
    conversations are a deliberate CASCADE and go with them.

    Their name stays on past transcripts — ``participants.name`` is its
    own column, and only the ``user_id`` link is dropped. So the history
    of who said what is preserved; what disappears is the login.
    """
    target = _require_manageable_target(db, actor, user_id)
    if target.id == actor.id:
        # An org admin deleting themselves is how an organization ends up
        # unreachable, and the request is never what someone meant.
        raise HTTPException(
            status_code=400, detail="You cannot delete your own account."
        )
    _guard_last_org_admin(db, target, permissions.ROLE_MEMBER)

    email = target.email

    categories_reassigned = (
        db.query(Category)
        .filter(Category.user_id == target.id)
        .update({Category.user_id: actor.id}, synchronize_session=False)
    )
    meetings_detached = (
        db.query(Meeting)
        .filter(Meeting.user_id == target.id)
        .update({Meeting.user_id: None}, synchronize_session=False)
    )

    # Those were bulk updates, so the session's own copies are stale —
    # including `User.categories`, whose `delete-orphan` cascade would
    # otherwise re-delete the very categories just rescued.
    db.expire_all()

    db.delete(target)
    db.commit()
    logger.info(
        "Deleted user %s from org %s (reassigned %d categories, detached "
        "%d meetings) by %s",
        email, actor.organization_id, categories_reassigned,
        meetings_detached, actor.email,
    )
    return {
        "status": "ok",
        "deleted_id": user_id,
        "email": email,
        "categories_reassigned": categories_reassigned,
        "meetings_detached": meetings_detached,
    }


def _resolve_categories(
    db: Session, org_id: UUID, category_ids: list[int]
) -> list[Category]:
    """Load categories, rejecting any that aren't in this org.

    All-or-nothing: a partial grant caused by a typo'd ID is worse than
    an error, because the caller would believe the grant was complete.
    """
    if not category_ids:
        return []
    unique_ids = list(dict.fromkeys(category_ids))
    categories = (
        db.query(Category)
        .filter(Category.id.in_(unique_ids), Category.organization_id == org_id)
        .all()
    )
    if len(categories) != len(unique_ids):
        found = {c.id for c in categories}
        missing = [cid for cid in unique_ids if cid not in found]
        raise HTTPException(
            status_code=404, detail=f"Unknown categories: {missing}"
        )
    return categories


def send_invite(
    db: Session, user: User, password: str, *, invited_by: User
) -> mail_service.SendResult:
    """Email a newly created member their sign-in details.

    Best-effort by design. The account is already committed by the time
    this runs, so a mail failure must not undo it — the caller reports the
    outcome and the UI falls back to showing the password for manual
    sharing. Returns the result rather than raising for the same reason.
    """
    org = user.organization
    text_body, html_body = mail_templates.invite_bodies(
        recipient_name=user.name,
        email=user.email,
        password=password,
        access_role=permissions.access_role(user),
        organization_name=org.name if org else None,
        invited_by_name=invited_by.name,
    )
    result = mail_service.send_email(
        to=user.email,
        subject=mail_templates.invite_subject(org.name if org else None),
        text_body=text_body,
        html_body=html_body,
    )
    logger.info(
        "Invite email %s for %s (by %s)", result.status, user.email, invited_by.email
    )
    return result


def _resolve_teams(db: Session, org_id: UUID, team_ids: list[int]) -> list[Team]:
    """Load teams, rejecting any outside this org. All-or-nothing, same
    reasoning as :func:`_resolve_categories`."""
    if not team_ids:
        return []
    unique_ids = list(dict.fromkeys(team_ids))
    teams = (
        db.query(Team)
        .join(Category, Team.category_id == Category.id)
        .filter(Team.id.in_(unique_ids), Category.organization_id == org_id)
        .all()
    )
    if len(teams) != len(unique_ids):
        found = {t.id for t in teams}
        missing = [tid for tid in unique_ids if tid not in found]
        raise HTTPException(status_code=404, detail=f"Unknown teams: {missing}")
    return teams


def _replace_grants(
    db: Session,
    user: User,
    categories: list[Category],
    *,
    granted_by: User,
    teams: Optional[list[Team]] = None,
    keep: Optional[set[tuple[int, Optional[int]]]] = None,
) -> None:
    """Make the user's grants exactly ``categories`` + ``teams``.

    A grant is a ``(category_id, team_id)`` pair where a NULL team means
    the whole category. ``categories`` become whole-category grants;
    ``teams`` become team-scoped grants keyed to each team's own parent
    category, which is why the caller passes teams rather than pairs — the
    parent is derived here so it cannot be spoofed.

    Replace rather than merge, so the caller can drive this straight from
    a multi-select: what the org admin sees ticked is what the user ends
    up with. Rows that survive are left untouched so their ``created_at``
    and ``granted_by`` audit values persist.

    A team whose category is ALSO granted in full is dropped — the
    category grant already covers it, and keeping both would leave two
    rows saying the same thing, with the narrower one implying a limit
    that isn't real.

    ``keep`` is added to the wanted set untouched. It exists for
    delegated administration: a category admin editing someone's scope
    submits only the categories they can see, and grants outside their
    scope must survive that edit rather than being silently revoked by
    an omission the actor could not have avoided.
    """
    whole_category_ids = {c.id for c in categories}
    team_pairs = {
        (t.category_id, t.id)
        for t in (teams or [])
        if t.category_id not in whole_category_ids
    }
    wanted = {(cid, None) for cid in whole_category_ids} | team_pairs | (keep or set())

    current = (
        db.query(CategoryAdmin).filter(CategoryAdmin.user_id == user.id).all()
    )
    held = set()
    for row in current:
        key = (row.category_id, row.team_id)
        if key in wanted:
            held.add(key)
        else:
            db.delete(row)

    for category_id, team_id in wanted - held:
        db.add(
            CategoryAdmin(
                category_id=category_id,
                team_id=team_id,
                user_id=user.id,
                granted_by_user_id=granted_by.id,
            )
        )
    db.flush()


def list_grantable_categories(db: Session, actor: User) -> list[dict]:
    """The option list for the grant picker: what this actor can hand out.

    An org admin sees every category in the org with all of its teams —
    deliberately unfiltered, unlike ``GET /categories``, since someone
    handing out rights has to see everything there is to hand out,
    including categories they would not otherwise be shown.

    A category admin sees only their own scope, and a category they hold
    only *some* teams of comes back carrying just those teams. The picker
    then cannot offer them anything they don't hold, and
    ``assert_grants_within_scope`` refuses it server-side if they try
    anyway.
    """
    scope = permissions.grant_scope(db, actor)

    query = (
        db.query(Category)
        .options(joinedload(Category.teams))
        .filter(Category.organization_id == actor.organization_id)
    )

    if scope is None:
        rows = query.order_by(Category.name.asc()).all()
        return [_category_option(c, c.teams or []) for c in rows]

    held_categories, held_teams = scope
    if not held_categories and not held_teams:
        return []

    # Categories reached either way: held in full, or holding a held team.
    reachable = set(held_categories)
    if held_teams:
        parents = (
            db.query(Team.category_id)
            .filter(Team.id.in_(sorted(held_teams)))
            .all()
        )
        reachable.update(p[0] for p in parents)

    rows = (
        query.filter(Category.id.in_(sorted(reachable)))
        .order_by(Category.name.asc())
        .all()
    )
    out = []
    for c in rows:
        if c.id in held_categories:
            teams = c.teams or []
        else:
            teams = [t for t in (c.teams or []) if t.id in held_teams]
        out.append(_category_option(c, teams))
    return out


def _category_option(category: Category, teams) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "color": category.color,
        "teams": [
            {"id": t.id, "name": t.name}
            for t in sorted(teams, key=lambda t: (t.name or ""))
        ],
    }


# --------------------------------------------------------------------------
# Password lifecycle
# --------------------------------------------------------------------------


def reset_password(db: Session, actor: User, user_id: UUID) -> tuple[dict, str]:
    """Issue a new temporary password for someone else's account.

    Returns ``(serialized_user, temporary_password)``. The password is
    returned only here — the server keeps a bcrypt hash, so this response
    is the one and only chance to read it.

    Exists because the alternative was worse. A provisioned password is
    shown exactly once, and without a re-issue path the only recovery for
    a lost one was to delete the account and recreate it — which drops the
    ``participants.user_id`` links that make that person a member of every
    meeting they attended. Trading someone's entire meeting history for a
    forgotten password is not a recovery procedure.

    Two consequences worth being deliberate about:

    * ``must_change_password`` goes back on. The actor now knows a working
      credential for an account that isn't theirs, so it is a delivery
      mechanism and nothing more — the API refuses everything outside the
      password-change allowlist until the owner replaces it.
    * every existing session for that user stops working. Bumping
      ``password_set_at`` revokes tokens issued before it (see
      ``dependencies/auth``), which is the point: a reset is most often a
      response to a credential someone else may hold.
    """
    target = _require_manageable_target(db, actor, user_id)
    if target.id == actor.id:
        # Their own password is `/auth/change-password`, which asks for the
        # current one. Routing self-service through here would hand them a
        # generated password and then lock them into the change screen.
        raise HTTPException(
            status_code=400,
            detail="Use the change-password page to set your own password.",
        )

    temporary_password = _generate_temporary_password()
    target.password = hash_password(temporary_password)
    target.must_change_password = True
    # Doubles as the revocation point for existing sessions, so it is set
    # even though the owner has not chosen this password themselves.
    target.password_set_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("Reset password for %s by %s", target.email, actor.email)
    return get_member(db, actor.organization_id, target.id), temporary_password


def change_password(
    db: Session, user: User, current_password: str, new_password: str
) -> dict:
    """Set a new password, clearing the forced-change flag.

    Verifies the current password even when ``must_change_password`` is
    set: the temporary password is the only thing proving the person at
    the keyboard is the intended recipient rather than someone who found
    an unattended session.
    """
    if not verify_password(current_password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )
    if verify_password(new_password, user.password):
        raise HTTPException(
            status_code=400,
            detail="New password must differ from the current one.",
        )
    user.password = hash_password(new_password)
    user.must_change_password = False
    user.password_set_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("Password changed for %s", user.email)
    return {"status": "ok"}
