"""Guards for the grant/role split in `app/services/permissions.py`.

Two properties, and both fail silently if broken — which is why they get
a test rather than a careful read:

1. **A grant widens what a MEMBER can see, and nothing else.** The view
   clauses must consult `category_admins` for every role; the manage
   clauses must consult it only for admins, and must render as an
   explicit deny for members rather than as TRUE.

2. **Nobody hands out access they don't hold.** A category admin who can
   grant an arbitrary category has full administration, one request away.

No database. The clause builders take a `Session` for signature
consistency but never touch it, so the SQL is compiled and inspected
directly — which is also the only way to catch a clause that has
degenerated into `TRUE`, since that reads as "no filter" at every call
site and looks like working code.

Run: `python tests/test_rbac_scopes.py`
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.db.models import CategoryAdmin, DocumentChunk, MeetingChunk, Team
from app.services import permissions
from app.utils.admin_enums import AccessRole, ParticipantMatchSource

ORG = uuid4()


def user(role: AccessRole) -> SimpleNamespace:
    """Enough of a User for the authorization helpers, which read only
    `id`, `organization_id` and `access_role`."""
    return SimpleNamespace(id=uuid4(), organization_id=ORG, access_role=role.value)


MEMBER = user(AccessRole.MEMBER)
ADMIN = user(AccessRole.ADMIN)
ORG_ADMIN = user(AccessRole.ORG_ADMIN)


def sql(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    )


# ---------------------------------------------------------------------------
# 1. Grants widen the view for every role
# ---------------------------------------------------------------------------

VIEW_CLAUSES = {
    "meeting": permissions.meeting_view_clause,
    "category": permissions.category_view_clause,
    "task": permissions.task_view_clause,
    "board": permissions.board_view_clause,
}

MANAGE_CLAUSES = {
    "meeting": permissions.meeting_manage_clause,
    "category": permissions.category_manage_clause,
    "task": permissions.task_manage_clause,
    "board": permissions.board_manage_clause,
}


def test_org_admin_is_unrestricted():
    for name, fn in {**VIEW_CLAUSES, **MANAGE_CLAUSES}.items():
        assert fn(None, ORG_ADMIN) is None, f"{name}: org admin must be unrestricted"


def test_member_view_honours_grants():
    """The regression this whole change exists to prevent: every view
    clause gated its grant arms behind `is_category_admin`, so a member's
    `category_admins` rows were dead data and an org admin could not
    scope a member without promoting them."""
    for name, fn in VIEW_CLAUSES.items():
        text = sql(fn(None, MEMBER))
        assert "category_admins" in text, (
            f"{name}_view_clause ignores grants for a MEMBER — scoping a "
            f"member would silently do nothing"
        )


def test_member_manage_never_derives_from_a_grant():
    """A grant must not become a write right. Whatever a member may edit,
    it cannot be because someone scoped them to a category."""
    for name, fn in MANAGE_CLAUSES.items():
        clause = fn(None, MEMBER)
        assert clause is not None, f"{name}: None means UNRESTRICTED, not denied"
        text = sql(clause).strip().lower()
        assert text not in ("true", "1 = 1"), f"{name}_manage_clause fails open"
        assert "category_admins" not in text, (
            f"{name}_manage_clause consults grants for a MEMBER — a scope "
            f"would become a promotion"
        )


def test_member_manage_is_explicit_deny_except_own_tasks():
    """Meetings, categories and boards are flatly denied to a member, and
    the deny must be a real false: an empty `and_()` renders as TRUE,
    which reads as "no filter" at every call site and hands write access
    to everyone.

    Tasks are the deliberate exception — a member may edit a task
    assigned to them, so that clause is narrow rather than empty.
    """
    for name in ("meeting", "category", "board"):
        text = sql(MANAGE_CLAUSES[name](None, MEMBER)).strip().lower()
        assert "is null" in text and "is not null" in text, (
            f"{name}_manage_clause is not the explicit-deny shape: {text}"
        )

    tasks = sql(MANAGE_CLAUSES["task"](None, MEMBER)).lower()
    assert "assignee_user_id" in tasks, (
        "a member lost the ability to edit tasks assigned to them"
    )


def test_admin_manage_honours_grants():
    for name, fn in MANAGE_CLAUSES.items():
        text = sql(fn(None, ADMIN))
        assert "category_admins" in text, f"{name}_manage_clause ignores ADMIN grants"


def test_team_view_clause_does_not_follow_from_category_reach():
    """Reaching a category must not enumerate its teams.

    `category_view_clause` deliberately uses `_reachable_category_ids`, so
    holding ONE team makes the parent category visible for navigation. If
    team visibility were derived from that, a narrow grant would list
    every sibling team — which is the opposite of what picking a team
    means.
    """
    for actor in (MEMBER, ADMIN):
        text = sql(permissions.team_view_clause(None, actor)).lower()
        assert "category_admins" in text, "team visibility ignores grants"
        # The whole-category arm must be the `team_id IS NULL` subquery,
        # not "any grant in this category".
        assert "team_id IS NULL".lower() in text, (
            "team_view_clause is not distinguishing whole-category grants "
            "from team-scoped ones"
        )
        assert "participants" in text, (
            "a team someone attended a meeting in should stay visible"
        )
    assert permissions.team_view_clause(None, ORG_ADMIN) is None


def test_category_list_filters_the_eager_team_collection():
    """`CategorySchema` renders `category.teams`, so an unfiltered eager
    load publishes the whole team list no matter what the clauses say. The
    filter has to be inside the join."""
    from sqlalchemy.orm import Session as OrmSession

    from app.db.models import Category
    from app.services import category_service

    session = OrmSession()
    for actor, expect_filtered in ((MEMBER, True), (ADMIN, True), (ORG_ADMIN, False)):
        statement = str(
            session.query(Category).options(
                category_service._visible_teams_option(session, actor)
            )
        )
        assert "LEFT OUTER JOIN teams" in statement, (
            "teams are no longer eager-loaded; a lazy load would bypass the "
            "filter entirely and return every team"
        )
        filtered = "category_admins" in statement
        assert filtered is expect_filtered, (
            f"{permissions.access_role(actor)}: team collection "
            f"{'should' if expect_filtered else 'should not'} be filtered"
        )


def test_chunk_clauses_are_scoped_for_members():
    """Retrieval is the surface where a leak is quotable verbatim, so the
    filter has to reach the chunk tables too."""
    meeting = sql(permissions.meeting_chunk_clause(None, MEMBER, MeetingChunk))
    assert "participants" in meeting, "meeting chunks not scoped to attendance"

    document = sql(permissions.document_chunk_clause(None, MEMBER, DocumentChunk))
    assert "category_admins" in document, "document chunks ignore member grants"
    # A team-only grant must reach that team's documents; without the
    # dedicated arm it vanishes, because the category subqueries report
    # whole-category grants only.
    assert document.count("category_admins") >= 2, (
        "document_chunk_clause is missing the team-grant arm"
    )


def test_org_admin_bypasses_chunk_filters():
    assert permissions.meeting_chunk_clause(None, ORG_ADMIN, MeetingChunk) is None
    assert permissions.document_chunk_clause(None, ORG_ADMIN, DocumentChunk) is None


# ---------------------------------------------------------------------------
# 2. Nobody grants what they don't hold
# ---------------------------------------------------------------------------


class FakeDb:
    """Answers the two queries the scope helpers make.

    Dispatches on the first selected column's name, which is enough to
    tell `CategoryAdmin.category_id` from `Team.id`.
    """

    def __init__(self, grants, team_parents):
        self._grants = grants               # [(category_id, team_id | None)]
        self._team_parents = team_parents   # {team_id: category_id}

    def query(self, *cols):
        return _FakeQuery(self, cols)


class _FakeQuery:
    def __init__(self, db, cols):
        self._db = db
        self._key = getattr(cols[0], "key", None)

    def filter(self, *_a, **_k):
        return self

    def all(self):
        if self._key == "category_id":
            return list(self._db._grants)
        if self._key == "id":
            return list(self._db._team_parents.items())
        raise AssertionError(f"unexpected query on {self._key!r}")


def expect_403(fn, *a, **k):
    try:
        fn(*a, **k)
    except HTTPException as e:
        assert e.status_code == 403, f"expected 403, got {e.status_code}"
        return e
    raise AssertionError("expected a 403, none raised")


def test_grant_scope_splits_whole_from_team():
    db = FakeDb(grants=[(1, None), (2, 20), (2, 21)], team_parents={})
    categories, teams = permissions.grant_scope(db, ADMIN)
    assert categories == {1}, "a team grant must not read as a whole category"
    assert teams == {20, 21}


def test_org_admin_scope_is_unbounded():
    assert permissions.grant_scope(FakeDb([], {}), ORG_ADMIN) is None


def test_admin_cannot_grant_a_category_they_do_not_hold():
    db = FakeDb(grants=[(1, None)], team_parents={})
    expect_403(
        permissions.assert_grants_within_scope,
        db, ADMIN, category_ids=[1, 99], team_ids=[],
    )
    # The held one alone is fine.
    permissions.assert_grants_within_scope(db, ADMIN, category_ids=[1], team_ids=[])


def test_admin_cannot_grant_a_team_outside_their_scope():
    # Holds category 1 in full, plus team 20 inside category 2.
    db = FakeDb(grants=[(1, None), (2, 20)], team_parents={10: 1, 20: 2, 21: 2})
    # Team 10 sits under a wholly-held category — allowed.
    permissions.assert_grants_within_scope(db, ADMIN, category_ids=[], team_ids=[10])
    # Team 20 is held directly — allowed.
    permissions.assert_grants_within_scope(db, ADMIN, category_ids=[], team_ids=[20])
    # Team 21 is a sibling of a held team, which confers nothing.
    expect_403(
        permissions.assert_grants_within_scope,
        db, ADMIN, category_ids=[], team_ids=[21],
    )
    # Holding one team confers nothing over its parent category.
    expect_403(
        permissions.assert_grants_within_scope,
        db, ADMIN, category_ids=[2], team_ids=[],
    )


def test_org_admin_may_grant_anything():
    db = FakeDb(grants=[], team_parents={7: 3})
    permissions.assert_grants_within_scope(
        db, ORG_ADMIN, category_ids=[1, 2, 3], team_ids=[7]
    )


def test_only_org_admin_mints_org_admins():
    from app.services import admin_service

    # Delegation is intended: an admin may promote to ADMIN.
    admin_service._assert_can_set_role(ADMIN, permissions.ROLE_ADMIN)
    admin_service._assert_can_set_role(ADMIN, permissions.ROLE_MEMBER)
    # ORG_ADMIN is scoped to nothing, so it is the one they cannot grant.
    expect_403(admin_service._assert_can_set_role, ADMIN, permissions.ROLE_ORG_ADMIN)
    admin_service._assert_can_set_role(ORG_ADMIN, permissions.ROLE_ORG_ADMIN)


def test_unknown_role_reads_as_least_privileged():
    """A stray value must deny rather than fail open or 500."""
    for bogus in (None, "", "superuser", "ORG_ADMIN ", 42):
        stray = SimpleNamespace(id=uuid4(), organization_id=ORG, access_role=bogus)
        if str(bogus).strip().upper() == "ORG_ADMIN":
            continue  # tolerant read of a real role, covered elsewhere
        assert permissions.meeting_manage_clause(None, stray) is not None, (
            f"access_role={bogus!r} must not be unrestricted"
        )


# ---------------------------------------------------------------------------
# 3. Deleting a user stays safe
# ---------------------------------------------------------------------------
#
# `admin_service.delete_member` is a hard delete, and what it has to clean
# up first is dictated entirely by the foreign keys pointing at `users`.
# The dangerous shape is NOT NULL + ON DELETE CASCADE: the row cannot be
# detached, so the delete propagates. `categories.user_id` is exactly that,
# and following it would destroy the category, its teams, its documents,
# its grants and the filing of every meeting in it.
#
# So this locks the schema down rather than the code. A migration that adds
# a new cascading FK into `users` fails here, which is the only moment
# anyone is going to think about it.

#: NOT NULL + CASCADE. Each one is a decision, not an accident.
_ACCEPTED_CASCADES = {
    # Reassigned to the actor by `delete_member` before the delete. This
    # is THE reason that function is not a bare `db.delete(user)`.
    ("categories", "user_id"),
    # Correct to follow: a grant is meaningless without its holder.
    ("category_admins", "user_id"),
    # Correct to follow: someone's own chat history goes with them.
    ("rag_conversations", "user_id"),
}

#: Nullable with NO `ondelete`, so Postgres would raise instead of
#: detaching. `delete_member` nulls these explicitly.
_ACCEPTED_MANUAL_DETACH = {("meetings", "user_id")}


def test_no_unreviewed_foreign_keys_into_users():
    from app.db.database import Base
    from app.db import models  # noqa: F401  (registers the mappers)

    surprises = []
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name != "users":
                continue
            key = (table.name, fk.parent.name)
            nullable = fk.parent.nullable
            ondelete = (fk.ondelete or "").upper()

            if ondelete == "SET NULL" and nullable:
                continue  # survives authorless, nothing to do
            if key in _ACCEPTED_CASCADES and not nullable and ondelete == "CASCADE":
                continue
            if key in _ACCEPTED_MANUAL_DETACH and nullable and not ondelete:
                continue
            surprises.append(
                f"{key[0]}.{key[1]} (nullable={nullable}, ondelete={ondelete or 'None'})"
            )

    assert not surprises, (
        "New or changed foreign key(s) into `users` that "
        "`admin_service.delete_member` does not account for:\n  "
        + "\n  ".join(surprises)
        + "\n\nDecide what deleting a user should do to these rows, handle it "
        "in `delete_member`, then add the key to `_ACCEPTED_CASCADES` or "
        "`_ACCEPTED_MANUAL_DETACH`. Leaving a NOT NULL + CASCADE unhandled "
        "means deleting an account silently deletes that row too."
    )


def test_delete_member_rescues_categories_before_deleting():
    """The rescue is easy to 'tidy away' into a bare `db.delete(user)`, and
    the damage would only show up as categories vanishing later. Assert the
    ordering is still in the source: reassign, then expire, then delete."""
    import inspect

    from app.services import admin_service

    # Body only. The docstring explains why this is not a bare
    # `db.delete(user)`, so searching the whole source matches the prose
    # instead of the code.
    src = inspect.getsource(admin_service.delete_member).split('"""')[-1]
    reassign = src.find("Category.user_id: actor.id")
    expire = src.find("expire_all")
    delete = src.find("db.delete(")
    assert reassign != -1, "delete_member no longer reassigns created categories"
    assert expire != -1, (
        "delete_member no longer expires the session — the stale "
        "`User.categories` collection would re-delete the rescued rows via "
        "its delete-orphan cascade"
    )
    assert reassign < expire < delete, (
        "delete_member's steps are out of order; the reassign and the "
        "expire must both precede the delete"
    )


# ---------------------------------------------------------------------------
# 4. Attendance → access, the input the MEMBER role runs on
# ---------------------------------------------------------------------------


def test_manual_links_are_trusted():
    """The manual override is only worth having if it actually grants.

    `manual` is what `link_participant` writes. Dropping it from the
    trusted set would leave the confirm button appearing to work while
    conferring nothing — the exact failure it exists to fix.
    """
    assert ParticipantMatchSource.MANUAL.value in permissions.TRUSTED_MATCH_SOURCES
    assert (
        ParticipantMatchSource.CALENDAR_EXACT.value
        in permissions.TRUSTED_MATCH_SOURCES
    )
    # The two that must NEVER grant: a fuzzy name-token hit, and the
    # migration's backfill of rows whose provenance is unknowable.
    assert ParticipantMatchSource.HEURISTIC.value not in permissions.TRUSTED_MATCH_SOURCES
    assert ParticipantMatchSource.LEGACY.value not in permissions.TRUSTED_MATCH_SOURCES


def test_grants_access_keys_off_provenance_not_the_link():
    """A row can carry a `user_id` and still confer nothing. Reporting the
    link as access is how a UI tells someone they have access when the
    query layer disagrees."""
    from app.services.meeting_service import _participant_dict

    def row(user_id, source):
        return SimpleNamespace(
            id=1, name="Chris", email="chris@example.com", is_organizer="False",
            avatar_url=None, created_at=None, user_id=user_id, match_source=source,
        )

    uid = uuid4()
    cases = {
        ("manual", uid): True,
        ("calendar_exact", uid): True,
        ("heuristic", uid): False,   # linked, but by guesswork
        ("legacy", uid): False,      # linked by the backfill
        ("manual", None): False,     # provenance without a link
        (None, None): False,
    }
    for (source, user_id), expected in cases.items():
        got = _participant_dict(row(user_id, source))["grants_access"]
        assert got is expected, (
            f"match_source={source!r} user_id={'set' if user_id else 'None'}: "
            f"grants_access should be {expected}, got {got}"
        )


def test_save_participants_resets_is_organizer_per_iteration():
    """`is_organizer` must be assigned INSIDE the per-participant loop.

    Two bugs live here, and both were shipped. Assigned nowhere, the
    reference below raises NameError on the first non-organizer — nearly
    every call — so no attendance rows are written and member access can
    never work. Assigned once ABOVE the loop, the first organizer match
    leaks onto everyone processed after them.
    """
    import ast
    import inspect
    import textwrap

    from app.pipelines.meeting_pipeline import MeetingPipeline

    # `getsource` on a method keeps its class indentation, which `ast.parse`
    # rejects outright.
    tree = ast.parse(
        textwrap.dedent(inspect.getsource(MeetingPipeline.save_participants))
    )
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)]
    # The participant loop is the one that constructs a Participant.
    target = [
        loop
        for loop in loops
        if any(
            isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "Participant"
            for n in ast.walk(loop)
        )
    ]
    assert target, "could not find the loop that creates Participant rows"

    assigned_in_loop = any(
        isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "is_organizer" for t in n.targets
        )
        and isinstance(n.value, ast.Constant)
        and n.value.value is False
        for n in ast.walk(target[0])
    )
    assert assigned_in_loop, (
        "`is_organizer = False` is not inside the participant loop — it must "
        "be reset per attendee, or the flag both NameErrors and goes sticky"
    )


# ---------------------------------------------------------------------------
# 5. A password reset actually ends the old sessions
# ---------------------------------------------------------------------------
#
# The JWT is stateless with a 7-day TTL, so there is nothing to delete when
# a password changes. `users.password_set_at` is the revocation point, and
# the comparison has to be wrong in neither direction: too strict and a
# fresh login invalidates itself, too loose and resetting a compromised
# account's password changes nothing for whoever holds the stolen cookie.


def test_tokens_carry_issued_at():
    from jose import jwt as jose_jwt

    from app.config.settings import settings
    from app.services.auth_service import create_token

    payload = jose_jwt.decode(
        create_token({"user_id": str(uuid4())}),
        settings.AUTH_SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )
    assert "iat" in payload, (
        "tokens have no `iat` claim, so a password change can no longer "
        "revoke anything — reset would silently leave sessions alive"
    )
    assert "exp" in payload


def test_password_change_revokes_older_tokens():
    from datetime import datetime, timedelta, timezone as tz

    from app.dependencies.auth import _issued_before_password_change

    now = datetime.now(tz.utc)

    def stub(changed_at):
        return SimpleNamespace(password_set_at=changed_at)

    # A token from before the change is refused. This is the whole feature.
    assert _issued_before_password_change(
        stub(now), (now - timedelta(hours=1)).timestamp()
    ), "a token predating the password change is still being accepted"

    # A token issued after it is fine.
    assert not _issued_before_password_change(
        stub(now - timedelta(hours=1)), now.timestamp()
    )

    # Same instant. `iat` is whole seconds while the column carries
    # microseconds, so without leeway a fresh login — and registration,
    # which stamps the column then immediately mints a token — would
    # invalidate itself on the spot.
    assert not _issued_before_password_change(stub(now), int(now.timestamp())), (
        "a token minted in the same second as the change is being rejected; "
        "login and registration would both break"
    )

    # Fail OPEN on the two unknowns: an account that has never set a
    # password, and a token minted before this check existed. Refusing the
    # latter would sign out every active session on deploy.
    assert not _issued_before_password_change(stub(None), now.timestamp())
    assert not _issued_before_password_change(stub(now), None)

    # A naive timestamp must be read as UTC, not the server's local zone —
    # otherwise the comparison shifts by hours and revokes (or fails to
    # revoke) depending on where the process happens to run.
    naive_past = (now - timedelta(hours=1)).replace(tzinfo=None)
    assert not _issued_before_password_change(stub(naive_past), now.timestamp())


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")


if __name__ == "__main__":
    main()
