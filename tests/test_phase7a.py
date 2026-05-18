"""Phase 7A ship test — Agent Control Dashboard scaffolding.

Architectural invariants verified:

  Schema:
   1. CHECK constraints reject bogus agent_type, status, scope_type
   2. CHECK constraint rejects (scope_type='category', scope_id NULL)
   3. CHECK constraint rejects (scope_type='organization', scope_id NOT NULL)
   4. Soft-active unique on (org, slug) — archive lets re-create
   5. Soft-active unique on (org, profile, scope_type, scope_id) — same
   6. Cascade: deleting an org wipes its profiles + configs + epochs
   7. Cascade: deleting a profile wipes its configs (and their epochs)

  HTTP — agent profiles:
   8. GET /agents/types returns the catalog (no auth required, but
      we still go through the auth-overridden client for consistency)
   9. POST /agents creates a profile, GET /agents lists it
  10. POST /agents rejects bogus slug shape (422 from Pydantic)
  11. POST /agents rejects unknown agent_type (422)
  12. POST /agents 409s on duplicate active slug
  13. PATCH /agents/{id} updates partial fields
  14. PATCH /agents/{id} refuses on archived profile (409)
  15. POST /agents/{id}/archive flips status; idempotent
  16. POST /agents/{id}/duplicate clones under new slug
  17. GET /agents tenant isolation (org A never sees org B's profiles)
  18. GET /agents/{id} cross-org returns 404

  HTTP — prompt configs:
  19. POST /prompt-configs creates an organization-scoped binding
  20. POST /prompt-configs creates a category-scoped binding
  21. POST /prompt-configs creates a team-scoped binding
  22. POST /prompt-configs rejects scope_id when scope_type='organization' (422)
  23. POST /prompt-configs requires scope_id when scope_type='category' (422)
  24. POST /prompt-configs rejects 'meeting_specific' (reserved for Phase 8)
  25. POST /prompt-configs 404s on cross-org category_id
  26. POST /prompt-configs 409s on duplicate active scope binding
  27. POST /prompt-configs/{id}/archive lets re-create same scope
  28. GET /prompt-configs filters by agent_profile / scope_type / status
  29. Tenant isolation on prompt-configs

Run with:

    venv\\Scripts\\python.exe tests\\test_phase7a.py
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
        msg = traceback.format_exc(limit=4).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Test fixtures — two orgs, each with a user + category + team.
# Same pattern as test_phase3d.py.
# ---------------------------------------------------------------------------


def _seed_org(theme: str) -> dict:
    """Build one org with: 1 user, 1 category, 1 team."""
    from app.db.database import SessionLocal
    from app.db.models import Category, Organization, Team, User

    db = SessionLocal()
    try:
        org = Organization(name=f"7a-{theme}-org")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"7a-{theme}",
            email=f"7a-{theme}-{uuid.uuid4()}@example.com",
            password="x",
            organization_id=org.id,
        )
        db.add(user); db.commit(); db.refresh(user)
        cat = Category(
            name=f"{theme}-cat", organization_id=org.id, user_id=user.id,
        )
        db.add(cat); db.commit(); db.refresh(cat)
        team = Team(name=f"{theme}-team", category_id=cat.id)
        db.add(team); db.commit(); db.refresh(team)
        return {
            "org_id": org.id, "user_id": user.id,
            "category_id": cat.id, "team_id": team.id,
            "theme": theme,
        }
    finally:
        db.close()


def _cleanup_all(fxs):
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        org_ids = [f["org_id"] for f in fxs]
        # Cascade from organizations handles the rest, but we explicitly
        # wipe the 7A tables first to make failures more informative.
        db.execute(sql_text(
            "DELETE FROM agent_config_epochs WHERE organization_id = ANY(:o)"
        ), {"o": org_ids})
        db.execute(sql_text(
            "DELETE FROM agent_prompt_configs WHERE organization_id = ANY(:o)"
        ), {"o": org_ids})
        db.execute(sql_text(
            "DELETE FROM agent_profiles WHERE organization_id = ANY(:o)"
        ), {"o": org_ids})
        db.execute(sql_text(
            "DELETE FROM teams WHERE id = ANY(:ids)"
        ), {"ids": [f["team_id"] for f in fxs]})
        db.execute(sql_text(
            "DELETE FROM categories WHERE id = ANY(:ids)"
        ), {"ids": [f["category_id"] for f in fxs]})
        db.execute(sql_text(
            "DELETE FROM users WHERE id = ANY(:ids)"
        ), {"ids": [f["user_id"] for f in fxs]})
        db.execute(sql_text(
            "DELETE FROM organizations WHERE id = ANY(:o)"
        ), {"o": org_ids})
        db.commit()
    finally:
        db.close()


def _client_for(user_id):
    """Build a TestClient with auth shimmed to return the named user."""
    from fastapi.testclient import TestClient
    from main import app
    from app.dependencies.auth import get_current_user
    from app.db.database import SessionLocal
    from app.db.models import User

    def fake_user():
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == user_id).first()
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = fake_user
    return TestClient(app)


# Lazy fixture handles populated in main().
_FX: list[dict] = []


def _A() -> dict:
    return _FX[0]


def _B() -> dict:
    return _FX[1]


# ===========================================================================
# Schema-layer tests
# ===========================================================================


def test_agent_profile_check_constraints():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile

    db = SessionLocal()

    def _bad(**overrides):
        defaults = dict(
            organization_id=_A()["org_id"],
            slug=f"bad-{uuid.uuid4().hex[:8]}",
            display_name="X",
            agent_type="rag_synth",
            status="active",
        )
        defaults.update(overrides)
        row = AgentProfile(**defaults)
        db.add(row)
        try:
            db.commit()
            return False
        except IntegrityError:
            db.rollback()
            return True

    try:
        assert _bad(agent_type="not_an_agent_type"), "bogus agent_type must violate CHECK"
        assert _bad(status="halfway"), "bogus status must violate CHECK"
    finally:
        db.close()


def test_prompt_config_check_constraints():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, AgentPromptConfig

    db = SessionLocal()
    try:
        # Need a profile in org A to bind to.
        prof = AgentProfile(
            organization_id=_A()["org_id"],
            slug=f"ck-{uuid.uuid4().hex[:8]}",
            display_name="P",
            agent_type="rag_synth",
        )
        db.add(prof); db.commit(); db.refresh(prof)

        def _bad(**overrides):
            defaults = dict(
                organization_id=_A()["org_id"],
                agent_profile_id=prof.id,
                scope_type="organization",
                scope_id=None,
                status="active",
            )
            defaults.update(overrides)
            row = AgentPromptConfig(**defaults)
            db.add(row)
            try:
                db.commit()
                return False
            except IntegrityError:
                db.rollback()
                return True

        assert _bad(scope_type="cosmic"), "bogus scope_type must violate CHECK"
        assert _bad(scope_type="organization", scope_id=42), \
            "organization scope must not carry scope_id"
        assert _bad(scope_type="category", scope_id=None), \
            "category scope must carry scope_id"
        assert _bad(scope_type="team", scope_id=None), \
            "team scope must carry scope_id"
        # Legal rows
        legal_org = AgentPromptConfig(
            organization_id=_A()["org_id"], agent_profile_id=prof.id,
            scope_type="organization", scope_id=None, status="active",
        )
        db.add(legal_org); db.commit()
        legal_cat = AgentPromptConfig(
            organization_id=_A()["org_id"], agent_profile_id=prof.id,
            scope_type="category", scope_id=_A()["category_id"], status="active",
        )
        db.add(legal_cat); db.commit()
        # Cleanup
        db.delete(legal_org); db.delete(legal_cat); db.delete(prof); db.commit()
    finally:
        db.close()


def test_soft_active_unique_slug_allows_re_create_after_archive():
    """Archiving frees the slug for a fresh active profile."""
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile

    db = SessionLocal()
    try:
        slug = f"reuse-{uuid.uuid4().hex[:8]}"
        a = AgentProfile(
            organization_id=_A()["org_id"], slug=slug,
            display_name="A", agent_type="rag_synth", status="active",
        )
        db.add(a); db.commit(); db.refresh(a)
        # Second active with same slug → violates partial unique
        b = AgentProfile(
            organization_id=_A()["org_id"], slug=slug,
            display_name="B", agent_type="rag_synth", status="active",
        )
        db.add(b)
        try:
            db.commit()
            raise AssertionError("duplicate active slug should be rejected")
        except IntegrityError:
            db.rollback()
        # Archive original; new active should succeed.
        a.status = "archived"
        db.commit()
        c = AgentProfile(
            organization_id=_A()["org_id"], slug=slug,
            display_name="C", agent_type="rag_synth", status="active",
        )
        db.add(c); db.commit(); db.refresh(c)
        # Cleanup
        db.delete(a); db.delete(c); db.commit()
    finally:
        db.close()


def test_soft_active_unique_scope_allows_re_create_after_archive():
    """Archiving a binding frees its (profile, scope) for a new one."""
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, AgentPromptConfig

    db = SessionLocal()
    try:
        prof = AgentProfile(
            organization_id=_A()["org_id"],
            slug=f"sa-{uuid.uuid4().hex[:8]}",
            display_name="P", agent_type="rag_synth",
        )
        db.add(prof); db.commit(); db.refresh(prof)
        a = AgentPromptConfig(
            organization_id=_A()["org_id"], agent_profile_id=prof.id,
            scope_type="team", scope_id=_A()["team_id"], status="active",
        )
        db.add(a); db.commit(); db.refresh(a)
        # Second active for same (profile, scope) — must fail.
        b = AgentPromptConfig(
            organization_id=_A()["org_id"], agent_profile_id=prof.id,
            scope_type="team", scope_id=_A()["team_id"], status="active",
        )
        db.add(b)
        try:
            db.commit()
            raise AssertionError("duplicate active binding should be rejected")
        except IntegrityError:
            db.rollback()
        # Archive first; second succeeds.
        a.status = "archived"; db.commit()
        c = AgentPromptConfig(
            organization_id=_A()["org_id"], agent_profile_id=prof.id,
            scope_type="team", scope_id=_A()["team_id"], status="active",
        )
        db.add(c); db.commit()
        # Cleanup (cascade via profile delete)
        db.delete(prof); db.commit()
    finally:
        db.close()


def test_cascade_org_delete_wipes_agent_rows():
    """Deleting an org cascades profiles + configs + epochs."""
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal
    from app.db.models import (
        AgentConfigEpoch, AgentProfile, AgentPromptConfig, Organization,
    )

    db = SessionLocal()
    try:
        org = Organization(name=f"7a-cascade-org-{uuid.uuid4().hex[:6]}")
        db.add(org); db.commit(); db.refresh(org)
        prof = AgentProfile(
            organization_id=org.id, slug="c-1",
            display_name="C", agent_type="rag_synth",
        )
        db.add(prof); db.commit(); db.refresh(prof)
        cfg = AgentPromptConfig(
            organization_id=org.id, agent_profile_id=prof.id,
            scope_type="organization", scope_id=None,
        )
        db.add(cfg); db.commit(); db.refresh(cfg)
        epoch = AgentConfigEpoch(
            organization_id=org.id, agent_profile_id=prof.id, epoch=1,
        )
        db.add(epoch); db.commit()

        # Capture ids and then cascade the org.
        org_id = org.id
        prof_id = prof.id
        cfg_id = cfg.id

        db.delete(org); db.commit(); db.expire_all()

        # Everything is gone.
        assert db.query(AgentProfile).filter(AgentProfile.id == prof_id).count() == 0
        assert db.query(AgentPromptConfig).filter(AgentPromptConfig.id == cfg_id).count() == 0
        n_epoch = db.execute(sql_text(
            "SELECT COUNT(*) FROM agent_config_epochs WHERE organization_id = :o"
        ), {"o": str(org_id)}).scalar()
        assert n_epoch == 0
    finally:
        db.close()


def test_cascade_profile_delete_wipes_configs():
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, AgentPromptConfig

    db = SessionLocal()
    try:
        prof = AgentProfile(
            organization_id=_A()["org_id"],
            slug=f"casc-{uuid.uuid4().hex[:8]}",
            display_name="P", agent_type="rag_synth",
        )
        db.add(prof); db.commit(); db.refresh(prof)
        cfg = AgentPromptConfig(
            organization_id=_A()["org_id"], agent_profile_id=prof.id,
            scope_type="team", scope_id=_A()["team_id"],
        )
        db.add(cfg); db.commit()
        cfg_id = cfg.id

        db.delete(prof); db.commit(); db.expire_all()
        assert db.query(AgentPromptConfig).filter(
            AgentPromptConfig.id == cfg_id,
        ).count() == 0
    finally:
        db.close()


# ===========================================================================
# HTTP-layer tests — agent profiles
# ===========================================================================


def test_get_agents_types_returns_catalog():
    client = _client_for(_A()["user_id"])
    resp = client.get("/agents/types")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = {it["agent_type"] for it in body}
    expected = {
        "rag_synth", "rag_planner", "graph_extractor", "transcript_analyzer",
        "importance_scorer", "summarizer", "live_copilot",
    }
    assert expected.issubset(types), f"missing types: {expected - types}"
    # live_copilot is the reserved one
    reserved = {it["agent_type"] for it in body if it["reserved"]}
    assert reserved == {"live_copilot"}, reserved


def test_post_agents_creates_and_get_lists():
    client = _client_for(_A()["user_id"])
    resp = client.post("/agents", json={
        "slug": "sales-copilot",
        "display_name": "Sales Copilot",
        "agent_type": "rag_synth",
        "description": "answers about deals",
    })
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["slug"] == "sales-copilot"
    assert created["agent_type"] == "rag_synth"
    assert created["status"] == "active"
    assert created["default_modular_prompt_json"] == {}

    listed = client.get("/agents").json()
    slugs = {it["slug"] for it in listed}
    assert "sales-copilot" in slugs


def test_post_agents_rejects_bogus_slug():
    client = _client_for(_A()["user_id"])
    resp = client.post("/agents", json={
        "slug": "Bad Slug!",  # uppercase + space + bang
        "display_name": "X",
        "agent_type": "rag_synth",
    })
    assert resp.status_code == 422, resp.text


def test_post_agents_rejects_unknown_agent_type():
    client = _client_for(_A()["user_id"])
    resp = client.post("/agents", json={
        "slug": "nope",
        "display_name": "X",
        "agent_type": "definitely-not-a-type",
    })
    assert resp.status_code == 422, resp.text


def test_post_agents_409_on_duplicate_slug():
    client = _client_for(_A()["user_id"])
    payload = {
        "slug": "dup-slug",
        "display_name": "Y",
        "agent_type": "rag_synth",
    }
    r1 = client.post("/agents", json=payload)
    assert r1.status_code == 201, r1.text
    r2 = client.post("/agents", json=payload)
    assert r2.status_code == 409, r2.text


def test_patch_agents_updates_partial_fields():
    client = _client_for(_A()["user_id"])
    create = client.post("/agents", json={
        "slug": "to-patch",
        "display_name": "Original",
        "agent_type": "rag_synth",
    })
    pid = create.json()["id"]
    resp = client.patch(f"/agents/{pid}", json={
        "display_name": "Renamed",
        "description": "updated",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "Renamed"
    assert body["description"] == "updated"
    # Slug + agent_type unchanged (and untouchable).
    assert body["slug"] == "to-patch"
    assert body["agent_type"] == "rag_synth"


def test_patch_archived_profile_409():
    client = _client_for(_A()["user_id"])
    create = client.post("/agents", json={
        "slug": "to-archive-then-patch",
        "display_name": "X",
        "agent_type": "rag_synth",
    })
    pid = create.json()["id"]
    arch = client.post(f"/agents/{pid}/archive")
    assert arch.status_code == 200, arch.text
    resp = client.patch(f"/agents/{pid}", json={"display_name": "should-fail"})
    assert resp.status_code == 409, resp.text


def test_archive_is_idempotent():
    client = _client_for(_A()["user_id"])
    create = client.post("/agents", json={
        "slug": "idempotent-archive",
        "display_name": "X",
        "agent_type": "rag_synth",
    })
    pid = create.json()["id"]
    r1 = client.post(f"/agents/{pid}/archive")
    r2 = client.post(f"/agents/{pid}/archive")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json()["status"] == "archived"


def test_duplicate_clones_profile():
    client = _client_for(_A()["user_id"])
    create = client.post("/agents", json={
        "slug": "to-duplicate",
        "display_name": "Source",
        "agent_type": "rag_synth",
        "description": "carries forward",
        "default_modular_prompt": {"system": "you are X"},
    })
    pid = create.json()["id"]
    dup = client.post(f"/agents/{pid}/duplicate", json={
        "new_slug": "duplicated",
        "new_display_name": "Copy",
    })
    assert dup.status_code == 201, dup.text
    body = dup.json()
    assert body["slug"] == "duplicated"
    assert body["display_name"] == "Copy"
    assert body["agent_type"] == "rag_synth"
    assert body["description"] == "carries forward"
    # Modular prompt carried forward.
    assert body["default_modular_prompt_json"]["system"] == "you are X"


def test_get_agents_tenant_isolation():
    # Each `_client_for(...)` re-applies the auth override, so we must
    # rebuild the client immediately before each request when switching
    # between users. FastAPI's `dependency_overrides` is a single shared
    # dict on the app — the last write wins.
    _client_for(_A()["user_id"]).post("/agents", json={
        "slug": "isolation-a", "display_name": "A",
        "agent_type": "rag_synth",
    })
    _client_for(_B()["user_id"]).post("/agents", json={
        "slug": "isolation-b", "display_name": "B",
        "agent_type": "rag_synth",
    })

    a_slugs = {it["slug"] for it in _client_for(_A()["user_id"]).get("/agents").json()}
    b_slugs = {it["slug"] for it in _client_for(_B()["user_id"]).get("/agents").json()}
    assert "isolation-a" in a_slugs and "isolation-b" not in a_slugs
    assert "isolation-b" in b_slugs and "isolation-a" not in b_slugs


def test_get_single_profile_cross_org_404():
    create = _client_for(_A()["user_id"]).post("/agents", json={
        "slug": "xorg-target", "display_name": "T",
        "agent_type": "rag_synth",
    })
    pid = create.json()["id"]
    # Org B can't see Org A's profile.
    resp = _client_for(_B()["user_id"]).get(f"/agents/{pid}")
    assert resp.status_code == 404, resp.text


# ===========================================================================
# HTTP-layer tests — prompt configs
# ===========================================================================


def _make_profile(client, slug: str) -> str:
    """Helper: create a profile and return its id."""
    r = client.post("/agents", json={
        "slug": slug, "display_name": slug, "agent_type": "rag_synth",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_post_prompt_config_organization_scope():
    client = _client_for(_A()["user_id"])
    pid = _make_profile(client, f"pc-org-{uuid.uuid4().hex[:6]}")
    r = client.post("/prompt-configs", json={
        "agent_profile_id": pid,
        "scope_type": "organization",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["scope_type"] == "organization"
    assert body["scope_id"] is None
    assert body["active_version_id"] is None  # filled in 7B


def test_post_prompt_config_category_scope():
    client = _client_for(_A()["user_id"])
    pid = _make_profile(client, f"pc-cat-{uuid.uuid4().hex[:6]}")
    r = client.post("/prompt-configs", json={
        "agent_profile_id": pid,
        "scope_type": "category",
        "scope_id": _A()["category_id"],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["scope_type"] == "category"
    assert body["scope_id"] == _A()["category_id"]


def test_post_prompt_config_team_scope():
    client = _client_for(_A()["user_id"])
    pid = _make_profile(client, f"pc-team-{uuid.uuid4().hex[:6]}")
    r = client.post("/prompt-configs", json={
        "agent_profile_id": pid,
        "scope_type": "team",
        "scope_id": _A()["team_id"],
    })
    assert r.status_code == 201, r.text


def test_post_prompt_config_org_with_scope_id_422():
    client = _client_for(_A()["user_id"])
    pid = _make_profile(client, f"pc-bad1-{uuid.uuid4().hex[:6]}")
    r = client.post("/prompt-configs", json={
        "agent_profile_id": pid,
        "scope_type": "organization",
        "scope_id": 42,
    })
    assert r.status_code == 422, r.text


def test_post_prompt_config_category_without_scope_id_422():
    client = _client_for(_A()["user_id"])
    pid = _make_profile(client, f"pc-bad2-{uuid.uuid4().hex[:6]}")
    r = client.post("/prompt-configs", json={
        "agent_profile_id": pid,
        "scope_type": "category",
    })
    assert r.status_code == 422, r.text


def test_post_prompt_config_meeting_specific_blocked():
    """Phase 8 reserves this scope; 7A's API rejects it explicitly."""
    client = _client_for(_A()["user_id"])
    pid = _make_profile(client, f"pc-ms-{uuid.uuid4().hex[:6]}")
    r = client.post("/prompt-configs", json={
        "agent_profile_id": pid,
        "scope_type": "meeting_specific",
    })
    assert r.status_code == 422, r.text


def test_post_prompt_config_cross_org_category_404():
    """Org A user binding a profile to Org B's category → 404."""
    client_a = _client_for(_A()["user_id"])
    pid = _make_profile(client_a, f"pc-xorg-{uuid.uuid4().hex[:6]}")
    r = client_a.post("/prompt-configs", json={
        "agent_profile_id": pid,
        "scope_type": "category",
        "scope_id": _B()["category_id"],
    })
    assert r.status_code == 404, r.text


def test_post_prompt_config_409_on_duplicate_scope():
    client = _client_for(_A()["user_id"])
    pid = _make_profile(client, f"pc-dup-{uuid.uuid4().hex[:6]}")
    body = {
        "agent_profile_id": pid,
        "scope_type": "team",
        "scope_id": _A()["team_id"],
    }
    r1 = client.post("/prompt-configs", json=body)
    assert r1.status_code == 201, r1.text
    r2 = client.post("/prompt-configs", json=body)
    assert r2.status_code == 409, r2.text


def test_archive_prompt_config_allows_re_create():
    client = _client_for(_A()["user_id"])
    pid = _make_profile(client, f"pc-rec-{uuid.uuid4().hex[:6]}")
    body = {
        "agent_profile_id": pid,
        "scope_type": "team",
        "scope_id": _A()["team_id"],
    }
    r1 = client.post("/prompt-configs", json=body)
    cid = r1.json()["id"]
    arch = client.post(f"/prompt-configs/{cid}/archive")
    assert arch.status_code == 200
    assert arch.json()["status"] == "archived"
    # Same scope binding can be re-created now.
    r2 = client.post("/prompt-configs", json=body)
    assert r2.status_code == 201, r2.text


def test_list_prompt_configs_filters():
    client = _client_for(_A()["user_id"])
    pid = _make_profile(client, f"pc-filter-{uuid.uuid4().hex[:6]}")
    # One of each scope type
    client.post("/prompt-configs", json={
        "agent_profile_id": pid, "scope_type": "organization",
    })
    client.post("/prompt-configs", json={
        "agent_profile_id": pid, "scope_type": "category",
        "scope_id": _A()["category_id"],
    })
    client.post("/prompt-configs", json={
        "agent_profile_id": pid, "scope_type": "team",
        "scope_id": _A()["team_id"],
    })
    # Filter by profile_id
    by_prof = client.get(
        f"/prompt-configs?agent_profile_id={pid}",
    ).json()
    assert len(by_prof) == 3, by_prof
    # Filter by scope_type
    only_team = client.get(
        f"/prompt-configs?agent_profile_id={pid}&scope_type=team",
    ).json()
    assert len(only_team) == 1, only_team


def test_prompt_configs_tenant_isolation():
    """Listing in Org B never returns Org A's bindings."""
    # Refresh `_client_for(...)` per-request — see note in
    # test_get_agents_tenant_isolation about the shared override dict.
    pid_a = _make_profile(
        _client_for(_A()["user_id"]), f"pc-iso-a-{uuid.uuid4().hex[:6]}",
    )
    pid_b = _make_profile(
        _client_for(_B()["user_id"]), f"pc-iso-b-{uuid.uuid4().hex[:6]}",
    )
    _client_for(_A()["user_id"]).post("/prompt-configs", json={
        "agent_profile_id": pid_a, "scope_type": "organization",
    })
    _client_for(_B()["user_id"]).post("/prompt-configs", json={
        "agent_profile_id": pid_b, "scope_type": "organization",
    })
    a_list = _client_for(_A()["user_id"]).get("/prompt-configs").json()
    a_profile_ids = {it["agent_profile_id"] for it in a_list}
    assert pid_a in a_profile_ids and pid_b not in a_profile_ids


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    global _FX
    _FX = [_seed_org("alpha"), _seed_org("bravo")]

    try:
        with section("7A - schema constraints"):
            check("7A", "agent_profiles CHECK rejects bogus agent_type/status",
                  test_agent_profile_check_constraints)
            check("7A", "agent_prompt_configs CHECK rejects bogus scope_type / scope_id mismatch",
                  test_prompt_config_check_constraints)
            check("7A", "soft-active unique (org, slug) allows re-create after archive",
                  test_soft_active_unique_slug_allows_re_create_after_archive)
            check("7A", "soft-active unique (org, profile, scope) allows re-create after archive",
                  test_soft_active_unique_scope_allows_re_create_after_archive)
            check("7A", "cascade: deleting an org wipes profiles + configs + epochs",
                  test_cascade_org_delete_wipes_agent_rows)
            check("7A", "cascade: deleting a profile wipes its configs",
                  test_cascade_profile_delete_wipes_configs)

        with section("7A - HTTP: agent profiles"):
            check("7A", "GET /agents/types returns catalog with live_copilot reserved",
                  test_get_agents_types_returns_catalog)
            check("7A", "POST /agents creates and GET /agents lists",
                  test_post_agents_creates_and_get_lists)
            check("7A", "POST /agents rejects bogus slug",
                  test_post_agents_rejects_bogus_slug)
            check("7A", "POST /agents rejects unknown agent_type",
                  test_post_agents_rejects_unknown_agent_type)
            check("7A", "POST /agents 409 on duplicate active slug",
                  test_post_agents_409_on_duplicate_slug)
            check("7A", "PATCH /agents/{id} updates partial fields",
                  test_patch_agents_updates_partial_fields)
            check("7A", "PATCH on archived profile 409",
                  test_patch_archived_profile_409)
            check("7A", "POST /agents/{id}/archive is idempotent",
                  test_archive_is_idempotent)
            check("7A", "POST /agents/{id}/duplicate clones profile",
                  test_duplicate_clones_profile)
            check("7A", "GET /agents tenant isolation",
                  test_get_agents_tenant_isolation)
            check("7A", "GET /agents/{id} cross-org returns 404",
                  test_get_single_profile_cross_org_404)

        with section("7A - HTTP: prompt configs"):
            check("7A", "POST /prompt-configs creates organization scope",
                  test_post_prompt_config_organization_scope)
            check("7A", "POST /prompt-configs creates category scope",
                  test_post_prompt_config_category_scope)
            check("7A", "POST /prompt-configs creates team scope",
                  test_post_prompt_config_team_scope)
            check("7A", "POST /prompt-configs rejects scope_id on organization (422)",
                  test_post_prompt_config_org_with_scope_id_422)
            check("7A", "POST /prompt-configs requires scope_id on category (422)",
                  test_post_prompt_config_category_without_scope_id_422)
            check("7A", "POST /prompt-configs rejects meeting_specific (Phase 8)",
                  test_post_prompt_config_meeting_specific_blocked)
            check("7A", "POST /prompt-configs cross-org category returns 404",
                  test_post_prompt_config_cross_org_category_404)
            check("7A", "POST /prompt-configs 409 on duplicate active scope",
                  test_post_prompt_config_409_on_duplicate_scope)
            check("7A", "archived prompt-config allows same-scope re-create",
                  test_archive_prompt_config_allows_re_create)
            check("7A", "GET /prompt-configs filters by profile + scope_type",
                  test_list_prompt_configs_filters)
            check("7A", "prompt-configs tenant isolation",
                  test_prompt_configs_tenant_isolation)
    finally:
        try:
            _cleanup_all(_FX)
        except Exception as e:
            print(f"  [cleanup error] {e}")

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
