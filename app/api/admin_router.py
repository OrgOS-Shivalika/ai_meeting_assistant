"""Organization member + admin management.

Every route here is org-admin-only. The guard is declared once as a
router-level dependency rather than repeated per handler, so a route
added later can't quietly ship without it.
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
    OrgMemberResponse,
    RoleUpdateRequest,
)
from app.services import admin_service, permissions


def _require_org_admin(user: User = Depends(get_current_user)) -> User:
    permissions.require_org_admin_role(user)
    return user


router = APIRouter(
    prefix="/admin",
    tags=["administration"],
    dependencies=[Depends(_require_org_admin)],
)


@router.get("/members", response_model=list[OrgMemberResponse])
def list_members(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Everyone in the organization, with their role, category grants and
    attendance count."""
    return admin_service.list_members(db, user.organization_id)


@router.get("/members/{user_id}", response_model=OrgMemberResponse)
def get_member(
    user_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return admin_service.get_member(db, user.organization_id, user_id)


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
    member, password, linked, email = admin_service.create_member(db, user, payload)
    return MemberCreateResponse(
        user=member,
        password=password,
        linked_meetings=linked,
        email_status=email.status,
        email_error=email.error,
    )


@router.post("/admins", response_model=AdminCreateResponse, status_code=201)
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
    password alone, so `temporary_password` comes back null.
    """
    member, temporary_password, email = admin_service.create_admin(db, user, payload)
    return AdminCreateResponse(
        user=member,
        temporary_password=temporary_password,
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
    `category_ids` replaces the set outright."""
    return admin_service.update_member(db, user, user_id, payload)


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
    """Every category in the org, each with its teams — the option list
    for the grant picker.

    Separate from `/categories` because that surface is access-filtered
    and this one deliberately isn't: an org admin handing out rights has
    to see everything they can hand out, including categories they
    themselves would not otherwise be shown.
    """
    from app.db.models import Category
    from sqlalchemy.orm import joinedload

    rows = (
        db.query(Category)
        .options(joinedload(Category.teams))
        .filter(Category.organization_id == user.organization_id)
        .order_by(Category.name.asc())
        .all()
    )
    return [
        {
            "id": c.id,
            "name": c.name,
            "color": c.color,
            "teams": [
                {"id": t.id, "name": t.name}
                for t in sorted(c.teams or [], key=lambda t: (t.name or ""))
            ],
        }
        for c in rows
    ]
