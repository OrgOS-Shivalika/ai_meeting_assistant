"""Members-page visibility: what a category admin is allowed to see.

The rule under test: a category admin sees the other admins of the
categories they administer, plus the members in those categories, and
never an org admin. An org admin still sees everyone.

Invariants verified:

   1. org admin's visible set is None (unrestricted)
   2. a category admin sees a fellow ADMIN granted the same category
   3. a category admin sees a MEMBER who attended a meeting in it
   4. a category admin does NOT see the org admin, even though that org
      admin attended a meeting in the managed category
   5. an ADMIN in a DIFFERENT category is not visible
   6. the actor always sees themselves
   7. list_members() agrees with the visible set (no org admin row)
   8. a team-only grant sees the team's people but not the org admin
   9. probing the org admin by id gives the same 403 text as any
      out-of-scope person — the message must not identify them
  10. an org admin CAN still fetch another user by id
  11. a category admin can create a member scoped to their own category,
      and can see + reopen them afterwards (the create-then-grant bug)
  12. a grant outside the actor's scope is refused, and leaves no account
  13. an unscoped create is refused for a category admin
  14. an unscoped create is allowed for an org admin

Run with:

    venv\\Scripts\\python.exe tests\\test_rbac_org_admin_concealment.py
"""
from __future__ import annotations

import os
import sys
import traceback
import uuid
from contextlib import contextmanager
from typing import Callable, List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# --------------------------------------------------------------------------
# No outbound mail from a test run
# --------------------------------------------------------------------------
#
# `create_member` sends an invite after committing, so once SMTP is
# configured — which it now is — these cases would post real mail to the
# `@example.com` addresses they invent. That domain is reserved and accepts
# nothing, so every run would bounce back into the sender's own inbox, add
# an SMTP round trip per case, and feed a stream of undeliverables to a
# live account's reputation.
#
# Stubbed rather than unset-the-env, because settings are read at import
# and a test that only passes with a particular `.env` is not a test. The
# replacement returns what an unconfigured server would, so the callers
# see the same `skipped` they were written against.
def _install_mail_stub() -> None:
    from app.services import mail_service

    def _no_send(**kwargs) -> "mail_service.SendResult":
        return mail_service.SendResult(sent=False, skipped=True)

    mail_service.send_email = _no_send  # type: ignore[assignment]


_install_mail_stub()


results: List[Tuple[str, str, str, str]] = []


@contextmanager
def section(label: str):
    print(f"\n=== {label} ===")
    yield


def check(slice_id: str, name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except AssertionError as e:
        msg = str(e) or "assertion failed"
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [FAIL] {name} :: {msg}")
        return
    except Exception:
        msg = traceback.format_exc(limit=8).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------
#
# One throwaway org holding the whole cast:
#
#   owner     ORG_ADMIN, and an attendee of the meeting in Alpha — so it is
#             attendance, not the role, that would otherwise pull them into
#             a category admin's list. That is the case worth testing.
#   alice     ADMIN over category Alpha  (the actor)
#   bob       ADMIN over category Alpha  (a peer she should see)
#   carol     MEMBER, attended the Alpha meeting
#   dave      ADMIN over category Beta   (out of scope)
#   erin      MEMBER, attended the Alpha meeting, granted team Alpha/Squad

_STATE: dict = {}


def _seed() -> dict:
    from app.db.database import SessionLocal
    from app.db.models import (
        Category, CategoryAdmin, Meeting, Organization, Participant, Team, User,
    )

    db = SessionLocal()
    try:
        tag = uuid.uuid4().hex[:6]
        org = Organization(name=f"rbac-conceal-{tag}")
        db.add(org)
        db.commit()
        db.refresh(org)
        # Published before the rest of the seed so a crash halfway through
        # still leaves `main` an org id to clean up. Without this an
        # exception here orphaned the org row.
        _STATE["org_id"] = org.id

        def mk_user(handle: str, role: str) -> User:
            u = User(
                name=f"{handle}-{tag}",
                email=f"{handle}-{uuid.uuid4()}@example.com",
                password="x",
                organization_id=org.id,
                access_role=role,
            )
            db.add(u)
            db.commit()
            db.refresh(u)
            return u

        owner = mk_user("owner", "ORG_ADMIN")
        alice = mk_user("alice", "ADMIN")
        bob = mk_user("bob", "ADMIN")
        carol = mk_user("carol", "MEMBER")
        dave = mk_user("dave", "ADMIN")
        erin = mk_user("erin", "MEMBER")

        # `categories.user_id` is NOT NULL — the creating user.
        alpha = Category(name=f"Alpha-{tag}", organization_id=org.id, user_id=owner.id)
        beta = Category(name=f"Beta-{tag}", organization_id=org.id, user_id=owner.id)
        db.add_all([alpha, beta])
        db.commit()
        db.refresh(alpha)
        db.refresh(beta)

        squad = Team(name=f"Squad-{tag}", category_id=alpha.id)
        db.add(squad)
        db.commit()
        db.refresh(squad)

        db.add_all([
            CategoryAdmin(category_id=alpha.id, user_id=alice.id, granted_by_user_id=owner.id),
            CategoryAdmin(category_id=alpha.id, user_id=bob.id, granted_by_user_id=owner.id),
            CategoryAdmin(category_id=beta.id, user_id=dave.id, granted_by_user_id=owner.id),
            CategoryAdmin(
                category_id=alpha.id, team_id=squad.id,
                user_id=erin.id, granted_by_user_id=owner.id,
            ),
        ])
        db.commit()

        # `meetings.meeting_url` is NOT NULL.
        meeting = Meeting(
            title=f"alpha standup {tag}",
            meeting_url=f"https://example.test/{tag}",
            organization_id=org.id,
            category_id=alpha.id,
            user_id=owner.id,
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)

        # `calendar_exact` is the trusted provenance — a heuristic link
        # confers nothing, so seeding one would make these assertions pass
        # for the wrong reason.
        for person in (owner, carol, erin):
            db.add(Participant(
                meeting_id=meeting.id,
                user_id=person.id,
                name=person.name,
                email=person.email,
                match_source="calendar_exact",
            ))
        db.commit()

        return {
            "org_id": org.id,
            "ids": {
                "owner": owner.id, "alice": alice.id, "bob": bob.id,
                "carol": carol.id, "dave": dave.id, "erin": erin.id,
            },
            "alpha_id": alpha.id,
            "beta_id": beta.id,
            "team_id": squad.id,
        }
    finally:
        db.close()


def _cleanup(org_id) -> None:
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        for stmt in (
            "DELETE FROM participants WHERE meeting_id IN "
            "  (SELECT id FROM meetings WHERE organization_id = :o)",
            "DELETE FROM meetings WHERE organization_id = :o",
            "DELETE FROM category_admins WHERE category_id IN "
            "  (SELECT id FROM categories WHERE organization_id = :o)",
            "DELETE FROM teams WHERE category_id IN "
            "  (SELECT id FROM categories WHERE organization_id = :o)",
            "DELETE FROM categories WHERE organization_id = :o",
            "DELETE FROM users WHERE organization_id = :o",
            "DELETE FROM organizations WHERE id = :o",
        ):
            db.execute(sql_text(stmt), {"o": str(org_id)})
        db.commit()
    finally:
        db.close()


@contextmanager
def _session():
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _user(db, handle):
    from app.db.models import User
    return db.query(User).filter(User.id == _STATE["ids"][handle]).first()


def _visible(db, handle):
    from app.services import permissions
    return permissions.admin_visible_user_ids(db, _user(db, handle))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_org_admin_unrestricted():
    with _session() as db:
        assert _visible(db, "owner") is None, "org admin should be unrestricted (None)"


def test_admin_sees_peer_admin():
    with _session() as db:
        assert _STATE["ids"]["bob"] in _visible(db, "alice"), \
            "a fellow admin of the same category must be visible"


def test_admin_sees_member_attendee():
    with _session() as db:
        assert _STATE["ids"]["carol"] in _visible(db, "alice"), \
            "a member who attended a meeting in the category must be visible"


def test_admin_cannot_see_org_admin():
    with _session() as db:
        visible = _visible(db, "alice")
        assert _STATE["ids"]["owner"] not in visible, (
            "ORG ADMIN LEAKED: the owner attended a meeting in Alpha, so "
            "attendance pulled them in and the concealment did not remove them"
        )


def test_admin_cannot_see_other_category_admin():
    with _session() as db:
        assert _STATE["ids"]["dave"] not in _visible(db, "alice"), \
            "an admin of a different category must not be visible"


def test_actor_sees_self():
    with _session() as db:
        assert _STATE["ids"]["alice"] in _visible(db, "alice"), \
            "the actor must always appear in their own list"


def test_list_members_hides_org_admin():
    from app.services import admin_service
    with _session() as db:
        rows = admin_service.list_members(db, _user(db, "alice"))
        roles = {str(r["id"]): r["access_role"] for r in rows}
        assert str(_STATE["ids"]["owner"]) not in roles, \
            "list_members returned the org admin row"
        assert "ORG_ADMIN" not in roles.values(), \
            "list_members returned some ORG_ADMIN row"
        assert str(_STATE["ids"]["bob"]) in roles, \
            "list_members dropped a peer admin it should include"


def test_team_only_grant_hides_org_admin():
    """A team-scoped actor reaches fewer people, and still no org admin."""
    with _session() as db:
        visible = _visible(db, "erin")
        assert _STATE["ids"]["owner"] not in visible, \
            "team-scoped actor saw the org admin"
        assert _STATE["ids"]["erin"] in visible, "team-scoped actor lost themselves"


def test_probe_by_id_does_not_identify_org_admin():
    """The 403 for the org admin must read the same as for anyone else.

    Otherwise a category admin can enumerate ids and pick out the org
    admin from the error text alone, defeating the concealment.
    """
    from fastapi import HTTPException
    from app.services import admin_service

    with _session() as db:
        actor = _user(db, "alice")

        def detail_for(handle: str) -> str:
            try:
                admin_service.get_member_for_actor(db, actor, _STATE["ids"][handle])
            except HTTPException as e:
                return str(e.detail)
            raise AssertionError(f"expected {handle} to be refused")

        owner_detail = detail_for("owner")
        dave_detail = detail_for("dave")
        assert owner_detail == dave_detail, (
            "org admin refusal is distinguishable from an ordinary "
            f"out-of-scope refusal: {owner_detail!r} vs {dave_detail!r}"
        )


def test_category_admin_can_create_scoped_member():
    """The reported bug: create-then-grant refused its own new account.

    A brand-new user holds no grant and has attended nothing, so they are
    outside the creator's visible set until the first grant exists. When
    grants were a follow-up PATCH, that call died with "That person is not
    in a category you manage" and left the account stranded.
    """
    from app.schemas.admin_schema import MemberCreateRequest
    from app.services import admin_service

    with _session() as db:
        actor = _user(db, "alice")
        # 4-tuple since the invite-email merge: (user, password, linked,
        # email_result). No mail leaves the process: `_install_mail_stub`
        # replaced the sender at import, so this reports 'skipped'.
        created, _pw, _linked, _mail = admin_service.create_member(
            db,
            actor,
            MemberCreateRequest(
                email=f"fresh-{uuid.uuid4()}@example.com",
                password="a-long-enough-password",
                access_role="MEMBER",
                category_ids=[_STATE["alpha_id"]],
            ),
        )
        assert [c["id"] for c in created["managed_categories"]] == [
            _STATE["alpha_id"]
        ], "the grant did not land in the same transaction"

        # And the creator can actually see and re-edit them afterwards.
        visible = _visible(db, "alice")
        assert created["id"] in visible, "creator cannot see the member they created"
        again = admin_service.get_member_for_actor(db, actor, created["id"])
        assert str(again["id"]) == str(created["id"]), \
            "creator cannot re-open the member they created"


def test_category_admin_cannot_create_out_of_scope():
    """Grants outside the actor's own scope are refused, and refused
    BEFORE the account is written — no orphan left behind."""
    from fastapi import HTTPException
    from app.db.models import User as UserModel
    from app.schemas.admin_schema import MemberCreateRequest
    from app.services import admin_service

    email = f"stray-{uuid.uuid4()}@example.com"
    with _session() as db:
        actor = _user(db, "alice")
        # Beta is dave's category, not alice's.
        beta_id = _STATE["beta_id"]
        try:
            admin_service.create_member(
                db,
                actor,
                MemberCreateRequest(
                    email=email,
                    password="a-long-enough-password",
                    access_role="MEMBER",
                    category_ids=[beta_id],
                ),
            )
            raise AssertionError("expected a refusal for an out-of-scope grant")
        except HTTPException as e:
            assert e.status_code == 403, f"expected 403, got {e.status_code}"
        db.rollback()

    with _session() as db:
        leftover = db.query(UserModel).filter(UserModel.email == email).first()
        assert leftover is None, "a rejected grant still created the account"


def test_category_admin_must_scope_new_member():
    """Creating with no scope at all is refused for a category admin: the
    account would be invisible to its own creator."""
    from fastapi import HTTPException
    from app.schemas.admin_schema import MemberCreateRequest
    from app.services import admin_service

    with _session() as db:
        try:
            admin_service.create_member(
                db,
                _user(db, "alice"),
                MemberCreateRequest(
                    email=f"nowhere-{uuid.uuid4()}@example.com",
                    password="a-long-enough-password",
                    access_role="MEMBER",
                ),
            )
            raise AssertionError("expected a refusal for an unscoped create")
        except HTTPException as e:
            assert e.status_code == 400, f"expected 400, got {e.status_code}"
        db.rollback()


def test_org_admin_may_create_unscoped():
    """The same call is fine for an org admin — they see everyone."""
    from app.schemas.admin_schema import MemberCreateRequest
    from app.services import admin_service

    with _session() as db:
        # 4-tuple since the invite-email merge: (user, password, linked,
        # email_result). No mail leaves the process: `_install_mail_stub`
        # replaced the sender at import, so this reports 'skipped'.
        created, _pw, _linked, _mail = admin_service.create_member(
            db,
            _user(db, "owner"),
            MemberCreateRequest(
                email=f"unscoped-{uuid.uuid4()}@example.com",
                password="a-long-enough-password",
                access_role="MEMBER",
            ),
        )
        assert created["managed_categories"] == [], "expected no grants"


def test_org_admin_can_fetch_anyone():
    from app.services import admin_service
    with _session() as db:
        row = admin_service.get_member_for_actor(
            db, _user(db, "owner"), _STATE["ids"]["alice"]
        )
        assert str(row["id"]) == str(_STATE["ids"]["alice"]), \
            "org admin could not fetch a user by id"


def main() -> int:
    global _STATE
    try:
        _STATE = _seed()

        with section("visibility set"):
            check("RBAC", "org admin unrestricted", test_org_admin_unrestricted)
            check("RBAC", "sees peer admin", test_admin_sees_peer_admin)
            check("RBAC", "sees member attendee", test_admin_sees_member_attendee)
            check("RBAC", "org admin concealed", test_admin_cannot_see_org_admin)
            check("RBAC", "other category's admin hidden",
                  test_admin_cannot_see_other_category_admin)
            check("RBAC", "actor sees self", test_actor_sees_self)
            check("RBAC", "team-only grant conceals too",
                  test_team_only_grant_hides_org_admin)

        with section("service surface"):
            check("RBAC", "list_members hides org admin",
                  test_list_members_hides_org_admin)
            check("RBAC", "refusal text does not identify org admin",
                  test_probe_by_id_does_not_identify_org_admin)
            check("RBAC", "org admin can fetch anyone",
                  test_org_admin_can_fetch_anyone)

        with section("create member (delegated)"):
            check("RBAC", "category admin creates a scoped member",
                  test_category_admin_can_create_scoped_member)
            check("RBAC", "out-of-scope grant refused, no orphan account",
                  test_category_admin_cannot_create_out_of_scope)
            check("RBAC", "unscoped create refused for category admin",
                  test_category_admin_must_scope_new_member)
            check("RBAC", "org admin may create unscoped",
                  test_org_admin_may_create_unscoped)
    except Exception as e:
        print(f"\n[driver crash] {e}")
        traceback.print_exc()
    finally:
        if _STATE.get("org_id") is not None:
            _cleanup(_STATE["org_id"])

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
