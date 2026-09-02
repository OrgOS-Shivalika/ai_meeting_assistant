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
    # The activation link, returned once so the creator can pass it on when
    # mail is unconfigured or bounces. It is a bearer credential for setting
    # the password — but it is single-use, time-limited, and the admin could
    # re-provision the account anyway, so handing it to them adds no power
    # they did not already have. A PASSWORD in the same slot did: it survived
    # in an inbox indefinitely and was the account's real credential.
    #
    # Null when an existing account was promoted — that path reuses their
    # login and issues no invitation.
    invite_url: Optional[str] = None
    email_status: str = "skipped"
    email_error: Optional[str] = None


class MemberCreateRequest(BaseModel):
    """Add a user to the caller's organization with a chosen role.

    **No password field, deliberately.** The creator used to pick one and
    pass it on out of band, which meant the account's first credential was a
    secret another person knew and an email server had carried. Provisioning
    now sends a single-use activation link and the owner chooses a password
    the server has never seen.

    Removing the field is the enforcement: there is no request shape that can
    set someone else's password, so no future caller can reintroduce the
    flow by accident.
    """
    email: EmailStr

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
    # Scope, applied in the same transaction as the account.
    #
    # Not a second request on purpose. A brand-new user holds no grants and
    # has attended nothing, so they fall outside a category admin's
    # visible set — which made the follow-up `PATCH /admin/members/{id}`
    # refuse with "That person is not in a category you manage" and strand
    # the account that had just been created. Mirrors
    # `AdminCreateRequest`, which has always taken its grants inline.
    category_ids: List[int] = Field(default_factory=list)
    team_ids: List[int] = Field(default_factory=list)


class MemberCreateResponse(BaseModel):
    user: OrgMemberResponse
    # The activation link, so the creator can pass it on when mail is
    # unconfigured or bounces. Not a password: this is single-use and
    # time-limited, and it lets its holder SET a credential rather than
    # being one. Whoever created the account could re-provision it anyway,
    # so this grants them nothing new — a mailed password did.
    invite_url: str
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


class PasswordResetResponse(BaseModel):
    """A freshly issued temporary password, returned once.

    Same one-shot contract as `AdminCreateResponse.invite_url`: the
    server stores only a bcrypt hash, so if this value is missed the reset
    has to be run again.
    """
    user: OrgMemberResponse
    reset_url: str
    # Every session that user had is now refused — `password_set_at` moved,
    # and tokens issued before it no longer validate. Reported so the UI can
    # say so rather than leaving the admin to assume otherwise.
    sessions_revoked: bool = True
    # Whether the new password was emailed to them. 'sent' | 'skipped' |
    # 'failed'; 'skipped' just means no SMTP is configured. The admin needs
    # this to know whether passing the password on by hand is still their
    # job — a silently failed send otherwise reads as a delivered one.
    email_status: str = "skipped"
    email_error: Optional[str] = None


class MemberDeleteResponse(BaseModel):
    """What a member deletion actually did.

    The two counts are reported rather than swallowed because the delete
    touches rows the caller didn't name: a category the deleted person
    created is reassigned to whoever ran the delete (the column is NOT
    NULL and cascades, so it can neither be kept nor nulled), and meetings
    they scheduled lose their creator link. Both are survivable, and both
    are surprising if they happen silently.
    """
    status: str
    deleted_id: UUID
    email: str
    categories_reassigned: int = 0
    meetings_detached: int = 0


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
