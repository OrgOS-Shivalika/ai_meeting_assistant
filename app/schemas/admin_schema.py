"""Schemas for organization member + admin management."""
from datetime import datetime
from typing import ClassVar, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.utils.admin_enums import AccessRole
from app.utils.password_transport import EncodedPasswordModel


class CategoryRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TeamRef(BaseModel):
    """A team-scoped grant, with its parent category for context."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category_id: int
    category_name: Optional[str] = None


class OrgMemberResponse(BaseModel):
    """A user in the organization, as the Members page renders them."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    access_role: AccessRole
    must_change_password: bool
    created_at: Optional[datetime] = None
    # Populated for admins; empty for members and (meaninglessly) for org
    # admins, who implicitly reach every category.
    #
    # WHOLE-category grants only. A grant scoped to one team appears in
    # `managed_teams` instead — collapsing the two would make a team-level
    # admin look like they run the entire category.
    managed_categories: List[CategoryRef] = []
    managed_teams: List[TeamRef] = []
    # How many meetings this person attended — the Members page uses it
    # to distinguish real participants from provisioned-but-never-seen
    # accounts.
    meeting_count: int = 0


class AdminCreateRequest(BaseModel):
    """Provision an admin: create the account and grant it categories.

    No password field. The server generates one — letting the caller
    choose a password for someone else's account means the caller knows
    a credential the owner believes is private.
    """
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    category_ids: List[int] = Field(default_factory=list)
    team_ids: List[int] = Field(default_factory=list)


class AdminCreateResponse(BaseModel):
    user: OrgMemberResponse
    # Returned exactly once, at creation. Also emailed to the recipient
    # when SMTP is configured, but still returned regardless — mail can
    # bounce or be filtered, and without a fallback the account would have
    # to be re-provisioned.
    temporary_password: Optional[str] = None
    email_status: str = "skipped"
    email_error: Optional[str] = None


class MemberCreateRequest(EncodedPasswordModel):
    """Add a user to the caller's organization with a chosen role.

    The org admin sets the password here and passes it to the person out
    of band. That means the creator knows the credential, which is why
    the created account carries `must_change_password` — the shared
    secret is a delivery mechanism, not the person's real password.
    """
    email: EmailStr
    # Base64 on the wire, so the real 8..128 rule lives in `_password_rules`
    # and is checked after decoding. Declaring it here instead would measure
    # the envelope: a legitimate 128-character password encodes to 172
    # characters and would be rejected as too long.
    password: str = Field(max_length=1024)

    _password_fields: ClassVar[tuple[str, ...]] = ("password",)
    _password_rules: ClassVar[dict[str, tuple[int, int]]] = {
        "password": (8, 128),
    }
    # Typed as the enum so an unknown role is rejected by validation with a
    # 422 listing the valid values, instead of reaching the service and
    # coming back as a hand-written 400.
    access_role: AccessRole
    # Optional: `users.name` is NOT NULL, so when this is omitted the
    # service derives a display name from the email local-part. Sending
    # it explicitly is better whenever the real name is known.
    name: Optional[str] = Field(default=None, max_length=200)


class MemberCreateResponse(BaseModel):
    user: OrgMemberResponse
    # Echoed back so the UI can render the "copy this now" panel from the
    # server's response rather than from local form state — that way what
    # is displayed is what was actually stored.
    #
    # Still returned even when the invite email succeeded: mail can bounce
    # or land in spam, and the org admin having no fallback would mean
    # re-provisioning the account.
    password: str
    # Invite email outcome. 'sent' | 'skipped' | 'failed' —
    # 'skipped' means no SMTP is configured, which is an expected
    # deployment state and not an error worth alarming the user about.
    email_status: str = "skipped"
    email_error: Optional[str] = None
    # How many of this person's pre-existing meeting attendances were
    # linked to the new account (they may have been in meetings long
    # before having a login).
    linked_meetings: int = 0


class RoleUpdateRequest(BaseModel):
    """Change a user's role and/or their category grants.

    Both fields are optional; omitting one leaves it untouched. Sending
    `category_ids` replaces the whole grant set rather than merging, so
    the UI can drive it straight from a multi-select without needing a
    separate revoke call.
    """
    access_role: Optional[AccessRole] = None
    # Whole-category grants.
    category_ids: Optional[List[int]] = None
    # Team-scoped grants. Each team's parent category is derived
    # server-side, so only the team id is needed. Sending either list
    # replaces the entire grant set.
    team_ids: Optional[List[int]] = None


class PasswordChangeRequest(EncodedPasswordModel):
    current_password: str = Field(max_length=1024)
    # Base64 on the wire; the 8..128 rule is enforced against the decoded
    # value via `_password_rules`, not against its longer envelope.
    new_password: str = Field(max_length=1024)

    _password_fields: ClassVar[tuple[str, ...]] = (
        "current_password",
        "new_password",
    )
    _password_rules: ClassVar[dict[str, tuple[int, int]]] = {
        "new_password": (8, 128),
    }
