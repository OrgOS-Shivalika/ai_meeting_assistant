from enum import Enum


class AccessRole(str, Enum):
    """A user's meeting-access role, stored in ``users.access_role``.

    Distinct from ``users.role`` (Phase 7E: viewer / prompt_editor /
    org_admin), which governs the agent-prompt surfaces only. The two
    columns share the name 'org_admin' but not its meaning — do not use
    this enum for that column.
    """

    MEMBER = "MEMBER"

    ADMIN = "ADMIN"

    #: Organization-wide. Every meeting, task and board in the org.
    ORG_ADMIN = "ORG_ADMIN"

    def __str__(self) -> str:
        """Render as the bare value.

        Without this, `str(AccessRole.ADMIN)` is "AccessRole.ADMIN" — a
        `str`-mixin Enum keeps Enum's `__str__` (unlike `StrEnum`, 3.11+).
        That leaked into log lines and would leak into any f-string or
        error message built from a role. DB binding was always fine
        because the str mixin makes the value the actual string.
        """
        return self.value

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """All role values, for validation messages and CHECK constraints."""
        return tuple(r.value for r in cls)

    @classmethod
    def coerce(cls, value: object) -> "AccessRole":
        """Resolve any input to a role, defaulting to :attr:`MEMBER`.

        Safe-deny: an unknown, NULL or malformed value reads as the
        least-privileged role rather than raising. Call sites here are
        authorization checks, and a stray value must not be able to fail
        open — nor to 500 a request that should simply be denied.

        Case-insensitive on the way IN while writes are always canonical
        uppercase. Rows written before the uppercase migration hold
        'org_admin', and reading those as MEMBER would silently strip an
        org admin of their access if the migration were ever partially
        applied. Tolerant reads, strict writes.
        """
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.MEMBER
        try:
            return cls(str(value).strip().upper())
        except ValueError:
            return cls.MEMBER


class PromptRole(str, Enum):
    """A user's agent-prompt governance role, stored in ``users.role``.

    Phase 7E. Entirely separate from :class:`AccessRole`: this one gates
    the agent/prompt surfaces (drafts, publish, rollback, playground,
    audit log) and knows nothing about meetings. They coincidentally
    share the member name ``ORG_ADMIN``; being an org admin on one column
    does not imply it on the other.

    Ranked — each role includes everything below it:

        VIEWER < PROMPT_EDITOR < ORG_ADMIN

    NULL is permitted in the column and reads as :attr:`VIEWER`, the
    safe-deny default.
    """

    VIEWER = "VIEWER"

    PROMPT_EDITOR = "PROMPT_EDITOR"

    ORG_ADMIN = "ORG_ADMIN"

    def __str__(self) -> str:
        """See :meth:`AccessRole.__str__`."""
        return self.value

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """All role values, for validation messages and CHECK constraints."""
        return tuple(r.value for r in cls)

    @classmethod
    def coerce(cls, value: object) -> "PromptRole":
        """Resolve any input to a role, defaulting to :attr:`VIEWER`.

        Case-insensitive on read for the same reason as
        :meth:`AccessRole.coerce` — rows written before the uppercase
        migration hold lowercase values, and silently reading an
        ``org_admin`` as ``VIEWER`` would revoke access rather than
        preserve it.
        """
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.VIEWER
        try:
            return cls(str(value).strip().upper())
        except ValueError:
            return cls.VIEWER

    @property
    def rank(self) -> int:
        """Position in the privilege ordering, for `>=` style checks."""
        return {
            PromptRole.VIEWER: 0,
            PromptRole.PROMPT_EDITOR: 1,
            PromptRole.ORG_ADMIN: 2,
        }[self]


#: Which `participants.match_source` values may confer access.
#:
#: `participants.email` is derived by a fuzzy name-token heuristic in
#: `MeetingPipeline.save_participants` — fine for rendering an avatar,
#: unsafe as an authorization input, because two colleagues named "Chris"
#: collapse onto the same token. So a link only counts when we know how it
#: was made:
#:   'calendar_exact' — exact email or exact full displayName match
#:                      against the Google Calendar attendee list
#:   'manual'         — an admin attached this participant deliberately
#: 'heuristic' and 'legacy' links are retained for display and assignee
#: suggestions but grant nothing.
class ParticipantMatchSource(str, Enum):
    """How a ``participants`` row was linked to a user account."""

    CALENDAR_EXACT = "calendar_exact"
    MANUAL = "manual"
    HEURISTIC = "heuristic"
    LEGACY = "legacy"

    def __str__(self) -> str:
        """See :meth:`AccessRole.__str__`."""
        return self.value

    @classmethod
    def trusted(cls) -> tuple[str, ...]:
        """Sources that confer meeting access."""
        return (cls.CALENDAR_EXACT.value, cls.MANUAL.value)
