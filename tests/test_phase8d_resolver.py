"""Phase 8D ship test — ResolvedBehaviorProfile resolver.

Five-layer cognition resolution. Verifies:

  Layer presence + ordering:
   1. Empty org (no link, no overrides) -> resolves to global default
   2. Org with category link -> global + category template merged
   3. Org with category + team link -> both templates merged on global
   4. Category override beats category template
   5. Team override beats team template (later layer wins)
   6. Workspace with only overrides (no link) still merges with global

  Per-dimension merge semantics:
   7. dict dimension: shallow merge — overlay keys win, missing pass through
   8. master_prompt overlay keeps base sections that overlay didn't touch
   9. enabled_agents: union across layers (de-dupe, order-preserving)
  10. Empty incoming dict ({}) is treated as "no contribution"

  Trace:
  11. trace[] records each contributing layer in order
  12. Layers that contributed nothing don't appear in trace

  Sanity:
  13. to_dict() has every dimension key
  14. resolve never raises on missing org / missing template

Run with:

    venv\\Scripts\\python.exe tests\\test_phase8d_resolver.py
"""
from __future__ import annotations

import os
import sys
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
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
        msg = traceback.format_exc(limit=8).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_org(theme: str) -> dict:
    from app.db.database import SessionLocal
    from app.db.models import Organization, User
    db = SessionLocal()
    try:
        org = Organization(name=f"8d-{theme}-{uuid.uuid4().hex[:6]}")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"8d-{theme}",
            email=f"8d-{theme}-{uuid.uuid4()}@example.com",
            password="x", organization_id=org.id, role="org_admin",
        )
        db.add(user); db.commit(); db.refresh(user)
        return {"org_id": org.id, "user_id": user.id}
    finally:
        db.close()


def _seed_category(org_id, user_id) -> int:
    from app.db.database import SessionLocal
    from app.db.models import Category
    db = SessionLocal()
    try:
        cat = Category(
            organization_id=org_id, user_id=user_id,
            name=f"test-cat-{uuid.uuid4().hex[:6]}", description="",
        )
        db.add(cat); db.commit(); db.refresh(cat)
        return cat.id
    finally:
        db.close()


def _seed_team(category_id) -> int:
    """Create a teams row under an existing categories row (sub-team
    under a department, matching the 8G hierarchy)."""
    from app.db.database import SessionLocal
    from app.db.models import Team
    db = SessionLocal()
    try:
        team = Team(
            category_id=category_id,
            name=f"test-team-{uuid.uuid4().hex[:6]}", description="",
        )
        db.add(team); db.commit(); db.refresh(team)
        return team.id
    finally:
        db.close()


def _seed_link(org_id, cat_id, *, template_kind, template_slug, version="1.0.0"):
    """Create a workspace_template_links row.

    Note: entity_type mirrors template_kind here, so 'category' links
    point at categories.id and 'team' links point at teams.id. The
    resolver uses entity_type to pick the right table for lookup."""
    from app.db.database import SessionLocal
    from app.db.models import WorkspaceTemplateLink
    db = SessionLocal()
    try:
        link = WorkspaceTemplateLink(
            organization_id=org_id,
            entity_type=template_kind, entity_id_int=cat_id,
            source_template_kind=template_kind,
            source_template_slug=template_slug,
            source_template_version=version,
            provisioned_at=datetime.now(timezone.utc),
        )
        db.add(link); db.commit(); db.refresh(link)
        return link.id
    finally:
        db.close()


def _cleanup_org(org_id):
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        for stmt in (
            "DELETE FROM workspace_behavior_overrides WHERE organization_id = :o",
            "DELETE FROM workspace_template_links WHERE organization_id = :o",
            # teams cascades from categories when the org cascades, but
            # explicit delete here keeps the order deterministic.
            "DELETE FROM teams WHERE category_id IN (SELECT id FROM categories WHERE organization_id = :o)",
            "DELETE FROM categories WHERE organization_id = :o",
            "DELETE FROM users WHERE organization_id = :o",
            "DELETE FROM organizations WHERE id = :o",
        ):
            db.execute(sql_text(stmt), {"o": str(org_id)})
        db.commit()
    finally:
        db.close()


def _ensure_seed():
    """Apply the catalog seed in case prior tests cleared the DB."""
    from app.db.database import SessionLocal
    from app.services.templates.behavior_seed import seed_catalog
    db = SessionLocal()
    try:
        seed_catalog(db)
    finally:
        db.close()


# ===========================================================================
# Layer presence + ordering
# ===========================================================================


def test_empty_org_returns_global_default():
    from app.db.database import SessionLocal
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("empty")
    db = SessionLocal()
    try:
        prof = resolve_behavior_profile(db, organization_id=fx["org_id"])
        assert "action-item-manager" in prof.enabled_agents
        assert prof.master_prompt.get("system", "").startswith(
            "You are the AI meeting assistant"
        ), prof.master_prompt
        # Only global layer contributed
        layers = [t.layer for t in prof.trace]
        assert layers == ["global"], layers
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_category_link_merges_template():
    from app.db.database import SessionLocal
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("cat-link")
    cat_id = _seed_category(fx["org_id"], fx["user_id"])
    _seed_link(fx["org_id"], cat_id, template_kind="category",
               template_slug="security")
    db = SessionLocal()
    try:
        prof = resolve_behavior_profile(
            db, organization_id=fx["org_id"], category_id=cat_id,
        )
        # security profile's enabled_agents must be unioned in
        assert "incident-investigator" in prof.enabled_agents, prof.enabled_agents
        assert "action-item-manager" in prof.enabled_agents  # from global
        # category_template trace recorded
        layers = [t.layer for t in prof.trace]
        assert layers == ["global", "category_template"], layers
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_team_link_overlays_on_category():
    """When both a category link AND a team link exist, the team is
    layer 3 (after category template). Later layer wins per-field."""
    from app.db.database import SessionLocal
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("both-links")
    cat_id = _seed_category(fx["org_id"], fx["user_id"])
    team_id = _seed_team(cat_id)
    _seed_link(fx["org_id"], cat_id, template_kind="category",
               template_slug="sales")
    _seed_link(fx["org_id"], team_id, template_kind="team",
               template_slug="sales-engineering")
    db = SessionLocal()
    try:
        prof = resolve_behavior_profile(
            db, organization_id=fx["org_id"],
            category_id=cat_id, team_id=team_id,
        )
        layers = [t.layer for t in prof.trace]
        assert layers == [
            "global", "category_template", "team_template",
        ], layers
        # Both templates' enabled_agents unioned
        assert "sales-coach" in prof.enabled_agents       # from sales category
        assert "technical-analyst" in prof.enabled_agents  # from sales-engineering team
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_category_override_beats_template():
    """A workspace_behavior_overrides row at scope='category' overlays
    AFTER the category template. Its values win."""
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import set_override
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("cat-override")
    cat_id = _seed_category(fx["org_id"], fx["user_id"])
    _seed_link(fx["org_id"], cat_id, template_kind="category",
               template_slug="security")
    db = SessionLocal()
    try:
        # Override one master_prompt section
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="category", scope_id=cat_id,
            dimension="master_prompt", field="behavior",
            value="OVERRIDDEN BEHAVIOR SECTION",
            actor_user_id=fx["user_id"],
        )
        prof = resolve_behavior_profile(
            db, organization_id=fx["org_id"], category_id=cat_id,
        )
        assert prof.master_prompt["behavior"] == "OVERRIDDEN BEHAVIOR SECTION", \
            prof.master_prompt["behavior"]
        # Other sections from the template/global still present
        assert prof.master_prompt.get("system"), prof.master_prompt
        layers = [t.layer for t in prof.trace]
        assert "category_override" in layers, layers
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_team_override_beats_team_template():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import set_override
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("team-override")
    cat_id = _seed_category(fx["org_id"], fx["user_id"])
    team_id = _seed_team(cat_id)
    _seed_link(fx["org_id"], cat_id, template_kind="category",
               template_slug="executive")
    _seed_link(fx["org_id"], team_id, template_kind="team",
               template_slug="leadership")
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="team", scope_id=team_id,
            dimension="tone_and_personality", field="formality",
            value="WHISPER",
        )
        prof = resolve_behavior_profile(
            db, organization_id=fx["org_id"],
            category_id=cat_id, team_id=team_id,
        )
        assert prof.tone_and_personality["formality"] == "WHISPER", \
            prof.tone_and_personality
        layers = [t.layer for t in prof.trace]
        assert "team_override" in layers, layers
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_workspace_with_only_overrides_no_link():
    """Workspace that hasn't installed any templates but has set some
    overrides should still resolve cleanly — overrides skip the link
    layer."""
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import set_override
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("ov-only")
    cat_id = _seed_category(fx["org_id"], fx["user_id"])
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="category", scope_id=cat_id,
            dimension="master_prompt", field="behavior",
            value="bare-overrides workspace",
        )
        prof = resolve_behavior_profile(
            db, organization_id=fx["org_id"], category_id=cat_id,
        )
        assert prof.master_prompt["behavior"] == "bare-overrides workspace"
        # Global still applied
        assert "action-item-manager" in prof.enabled_agents
        layers = [t.layer for t in prof.trace]
        assert "global" in layers
        assert "category_override" in layers
        assert "category_template" not in layers, layers
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


# ===========================================================================
# Per-dimension merge semantics
# ===========================================================================


def test_dict_merge_keeps_untouched_keys():
    """If a layer's overlay only sets master_prompt.behavior, the
    lower layers' master_prompt.system MUST still be present."""
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import set_override
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("dict-merge")
    cat_id = _seed_category(fx["org_id"], fx["user_id"])
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="category", scope_id=cat_id,
            dimension="master_prompt", field="behavior", value="X",
        )
        prof = resolve_behavior_profile(
            db, organization_id=fx["org_id"], category_id=cat_id,
        )
        assert prof.master_prompt["behavior"] == "X"
        # system from global default
        assert prof.master_prompt.get("system"), prof.master_prompt
        # citation from global default
        assert prof.master_prompt.get("citation"), prof.master_prompt
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_enabled_agents_is_union():
    """enabled_agents merges as union, not replacement."""
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import set_override
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("agents-union")
    cat_id = _seed_category(fx["org_id"], fx["user_id"])
    _seed_link(fx["org_id"], cat_id, template_kind="category",
               template_slug="sales")
    db = SessionLocal()
    try:
        # Workspace adds a custom agent
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="category", scope_id=cat_id,
            dimension="enabled_agents", field="",
            value=["custom-summarizer"],
        )
        prof = resolve_behavior_profile(
            db, organization_id=fx["org_id"], category_id=cat_id,
        )
        # All three contributors present
        assert "action-item-manager" in prof.enabled_agents  # global
        assert "sales-coach" in prof.enabled_agents          # sales template
        assert "custom-summarizer" in prof.enabled_agents    # workspace override
        # No duplicates
        assert len(prof.enabled_agents) == len(set(prof.enabled_agents))
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


# ===========================================================================
# Trace + sanity
# ===========================================================================


def test_workspace_override_layer_bites():
    """Phase 9.0 — Workspace-scope overrides MUST be applied between the
    global default and the per-category templates. Previously they were
    silently stored but ignored."""
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import set_override
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("ws-override")
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"], scope_type="workspace",
            dimension="tone_and_personality", field="verbosity",
            value="very-concise",
        )
        prof = resolve_behavior_profile(db, organization_id=fx["org_id"])
        assert prof.tone_and_personality.get("verbosity") == "very-concise", \
            prof.tone_and_personality
        layers = [t.layer for t in prof.trace]
        assert "workspace_override" in layers, layers
        # Workspace_override must be between global and any other layer
        assert layers.index("workspace_override") == 1, layers
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_category_override_beats_workspace_override():
    """Layer ordering: workspace (1.5) < category template (2) <
    category override (4). A category override at a more-specific
    scope MUST win over a workspace-wide setting on the same key."""
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import set_override
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("ws-vs-cat")
    cat_id = _seed_category(fx["org_id"], fx["user_id"])
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"], scope_type="workspace",
            dimension="tone_and_personality", field="formality",
            value="casual",
        )
        set_override(
            db, organization_id=fx["org_id"], scope_type="category",
            scope_id=cat_id,
            dimension="tone_and_personality", field="formality",
            value="formal",
        )
        prof = resolve_behavior_profile(
            db, organization_id=fx["org_id"], category_id=cat_id,
        )
        # Category override wins
        assert prof.tone_and_personality.get("formality") == "formal", \
            prof.tone_and_personality
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_trace_records_contributing_layers_in_order():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import set_override
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("trace")
    cat_id = _seed_category(fx["org_id"], fx["user_id"])
    team_id = _seed_team(cat_id)
    _seed_link(fx["org_id"], cat_id, template_kind="category",
               template_slug="security")
    _seed_link(fx["org_id"], team_id, template_kind="team",
               template_slug="security-engineering")
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="category", scope_id=cat_id,
            dimension="output_config", field="format", value="json",
        )
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="team", scope_id=team_id,
            dimension="tone_and_personality", field="formality",
            value="terse",
        )
        prof = resolve_behavior_profile(
            db, organization_id=fx["org_id"],
            category_id=cat_id, team_id=team_id,
        )
        layers = [t.layer for t in prof.trace]
        assert layers == [
            "global", "category_template", "team_template",
            "category_override", "team_override",
        ], layers
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_to_dict_has_all_dimensions():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import BEHAVIOR_DIMENSIONS
    from app.services.behavior.resolver import resolve_behavior_profile
    _ensure_seed()
    fx = _seed_org("todict")
    db = SessionLocal()
    try:
        prof = resolve_behavior_profile(db, organization_id=fx["org_id"])
        d = prof.to_dict()
        for dim in BEHAVIOR_DIMENSIONS:
            assert dim in d, dim
        assert "trace" in d
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        with section("8D - layer presence + ordering"):
            check("8D", "empty org -> global default only",
                  test_empty_org_returns_global_default)
            check("8D", "category link merges template",
                  test_category_link_merges_template)
            check("8D", "team link overlays on category",
                  test_team_link_overlays_on_category)
            check("8D", "category override beats template",
                  test_category_override_beats_template)
            check("8D", "team override beats team template",
                  test_team_override_beats_team_template)
            check("8D", "workspace with only overrides resolves",
                  test_workspace_with_only_overrides_no_link)

        with section("8D - dimension merge semantics"):
            check("8D", "dict merge keeps untouched keys",
                  test_dict_merge_keeps_untouched_keys)
            check("8D", "enabled_agents is union",
                  test_enabled_agents_is_union)

        with section("8D - trace + sanity"):
            check("8D", "trace records 5 layers in order",
                  test_trace_records_contributing_layers_in_order)
            check("8D", "to_dict has all dimensions",
                  test_to_dict_has_all_dimensions)

        with section("9.0 - workspace override layer"):
            check("9.0", "workspace override layer applies",
                  test_workspace_override_layer_bites)
            check("9.0", "category override beats workspace override",
                  test_category_override_beats_workspace_override)
    except Exception as e:
        print(f"\n[driver crash] {e}")
        traceback.print_exc()

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
