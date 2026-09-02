"""Organization member + admin management.

Reachable by admins and org admins. The role guard is declared once as a
router-level dependency rather than repeated per handler, so a route
added later can't quietly ship without one.

That guard is the floor, not the whole rule. A category admin sees and
manages only people inside their own categories and teams, and cannot
mint an org admin; the scoping lives in `admin_service` because it needs
the database, and a dependency that answers "which users are in scope"
would have to run the same queries the service already runs.

The one exception is `POST /admins`, which provisions a brand-new admin
account with a generated password. That is org-structural — creating an
account is not the same as delegating rights over categories you already
hold — so it carries its own org-admin dependency on top.
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.dependencies.auth import get_current_user
from app.schemas.admin_schema import (
    AdminCreateRequest,
    AdminCreateResponse,
    MemberCreateRequest,
    MemberCreateResponse,
    MemberDeleteResponse,
    OrgMemberResponse,
    PasswordResetResponse,
    RoleUpdateRequest,
)
from app.services import admin_service, permissions


def _require_admin(user: User = Depends(get_current_user)) -> User:
    """Floor for the whole router: admin or org admin."""
    permissions.require_admin_role(user)
    return user


def _require_org_admin(user: User = Depends(get_current_user)) -> User:
    permissions.require_org_admin_role(user)
    return user


router = APIRouter(
    prefix="/admin",
    tags=["administration"],
    dependencies=[Depends(_require_admin)],
)


@router.get("/members", response_model=list[OrgMemberResponse])
def list_members(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """People the caller may administer, with their role, grants and
    attendance count.

    Org admins get the whole organization; a category admin gets the
    people inside their own categories and teams.
    """
    return admin_service.list_members(db, user)


@router.get("/members/{user_id}", response_model=OrgMemberResponse)
def get_member(
    user_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return admin_service.get_member_for_actor(db, user, user_id)


@router.post("/members", response_model=MemberCreateResponse, status_code=201)
def create_member(
    payload: MemberCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add a user to this organization with a chosen role and password.

    Backs the "Add Member" flow on the Members page. The password comes
    from the caller and is echoed back once in the response so the UI can
    show it for copying — it is stored only as a bcrypt hash, so this
    response is the last time it is ever retrievable.

    The new account is created with `must_change_password` set: the
    creator knows the password, so it works for first sign-in and nothing
    else until the owner replaces it.

    409 if the email already has an account anywhere. Promoting or
    re-roling an existing user goes through `PATCH /admin/members/{id}`.
    """
    member, invite_url, linked, email = admin_service.create_member(db, user, payload)
    return MemberCreateResponse(
        user=member,
        invite_url=invite_url,
        linked_meetings=linked,
        email_status=email.status,
        email_error=email.error,
    )


@router.post(
    "/admins",
    response_model=AdminCreateResponse,
    status_code=201,
    dependencies=[Depends(_require_org_admin)],
)
def create_admin(
    payload: AdminCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Provision an admin: create the account with a generated password
    and grant it the requested categories.

    Emails the person their sign-in details when SMTP is configured, and
    reports the outcome as `email_status`. Delivery is best-effort: a mail
    failure does NOT fail the request, because the account is already
    created by then.

    The password comes back in the response body **once**, whether or not
    the email went out — mail bounces and spam filters exist.

    Promoting someone who already has an account (common — they probably
    attended a meeting first) reuses that account and leaves their
    password alone, so `invite_url` comes back null.
    """
    member, invite_url, email = admin_service.create_admin(db, user, payload)
    return AdminCreateResponse(
        user=member,
        invite_url=invite_url,
        email_status=email.status if email else "skipped",
        email_error=email.error if email else None,
    )


@router.patch("/members/{user_id}", response_model=OrgMemberResponse)
def update_member(
    user_id: UUID,
    payload: RoleUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Change a role and/or replace the category grants. Sending
    `category_ids` replaces the set outright.

    Grants and roles are independent: scoping a plain member to a
    category gives them read access to it and leaves them a member.
    Promotion is a separate `access_role` change in the same request or
    another one.
    """
    return admin_service.update_member(db, user, user_id, payload)


@router.post(
    "/members/{user_id}/reset-password", response_model=PasswordResetResponse
)
def reset_password(
    user_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Issue a new temporary password for a member.

    Emails it to them when SMTP is configured, and reports the outcome as
    `email_status`. Delivery is best-effort: a mail failure does NOT fail
    the request, because the password has already been changed by then.

    The password also comes back in the body **once**, whether or not the
    email went out — mail bounces and spam filters exist, and the server
    keeps only a hash.

    Two things happen that are worth telling the user about: the account
    goes back into forced-password-change, and every session that person
    had stops working immediately. The second is usually the reason
    someone is here.

    Before this existed the only fix for a lost password was to delete and
    recreate the account, which discards the attendance links that give
    that person access to their own meeting history.
    """
    member, reset_url, email = admin_service.reset_password(
        db, user, user_id
    )
    return PasswordResetResponse(
        user=member,
        reset_url=reset_url,
        sessions_revoked=True,
        email_status=email.status,
        email_error=email.error,
    )


@router.delete("/members/{user_id}", response_model=MemberDeleteResponse)
def delete_member(
    user_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete an account outright.

    Distinct from `DELETE /members/{id}/admin`, which only demotes. Use
    this to clear out accounts that should not exist — a typo'd email, a
    provisioning attempt that half-failed.

    The person's meeting history survives: `participants.name` is its own
    column and only the account link is dropped. Categories they created
    are reassigned to you, because that column cascades and would
    otherwise take the category and its teams, documents and grants down
    with the account.
    """
    return admin_service.delete_member(db, user, user_id)


@router.delete("/members/{user_id}/admin", response_model=OrgMemberResponse)
def revoke_admin(
    user_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Demote to member and drop all grants. The account and its meeting
    history survive."""
    return admin_service.revoke_admin(db, user, user_id)


@router.get("/categories")
def list_grantable_categories(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The option list for the grant picker — what this caller can hand
    out.

    For an org admin that is every category in the org with all of its
    teams, deliberately unfiltered unlike `GET /categories`. For a
    category admin it is their own scope only, so the picker can never
    offer them a category they don't hold.
    """
    return admin_service.list_grantable_categories(db, user)
