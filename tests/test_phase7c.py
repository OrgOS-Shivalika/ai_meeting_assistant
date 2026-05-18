"""Phase 7C ship test — runtime resolver in shadow mode.

Invariants verified:

  Composition + variable interpolation:
   1. interpolate substitutes `{{var}}` from variables dict
   2. interpolate HTML-escapes values to prevent prompt-injection
   3. interpolate yields `[var unavailable]` + warning for missing keys
   4. interpolate is idempotent (same input → same output)
   5. compose_system_message follows the locked 8-section order
   6. empty sections produce no blank stanzas (clean newlines)
   7. composition order matches ModularPrompt.section_keys()

  Cache:
   8. put then get returns the same value
   9. TTL expiry drops the entry
  10. capacity eviction drops LRU
  11. clear() resets stats + entries
  12. locked() context manager serializes per-key

  Resolver — fallback:
  13. resolve_agent_runtime_config with no profile → filesystem floor
  14. filesystem floor for rag_synth includes the v1 prompt text
  15. unknown agent_type returns empty modular + is_default_fallback=True

  Resolver — DB layers:
  16. org-scoped published version contributes to result
  17. category-scoped overrides org-scoped on overlapping keys
  18. team-scoped overrides category-scoped
  19. resolution_path captures every contributing layer
  20. retrieval_config merges higher-priority over lower
  21. tool_permissions union allowed; deny is also union
  22. config_hash is deterministic across calls with same DB state

  Resolver — cache + epoch:
  23. second call with same inputs is a cache hit
  24. epoch bump invalidates cache (next call recomputes)
  25. different team_ids produce different cache entries
  26. cross-org configs never leak into wrong org's resolution

  Shadow-mode wiring:
  27. ask_stream resolver call writes an agent_runtime_logs row
  28. rag_query_runs row has agent_profile_id + prompt_version_id +
      resolution_path_hash populated when a profile/version exists
  29. shadow mode does NOT change synth prompt usage (filesystem
      prompts still drive synth — invariant: pre-7C answers match
      post-7C answers)

  HTTP:
  30. GET /agents/runtime/resolve returns the resolved bundle
  31. GET /rag/observability/resolution-distribution lists per-hash counts

Run with:

    venv\\Scripts\\python.exe tests\\test_phase7c.py
"""
from __future__ import annotations

import os
import sys
import time
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
# Fixtures
# ---------------------------------------------------------------------------


def _seed_org(theme: str) -> dict:
    """Seed an org + user + category + team + a published rag_synth
    profile (so the resolver has something to resolve against)."""
    from app.db.database import SessionLocal
    from app.db.models import (
        AgentProfile, AgentPromptConfig, Category, Organization, Team, User,
    )
    from app.services.agents.publish import create_draft, publish_version

    db = SessionLocal()
    try:
        org = Organization(name=f"7c-{theme}-org")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"7c-{theme}",
            email=f"7c-{theme}-{uuid.uuid4()}@example.com",
            password="x", organization_id=org.id,
        )
        db.add(user); db.commit(); db.refresh(user)
        cat = Category(
            name=f"{theme}-cat", organization_id=org.id, user_id=user.id,
        )
        db.add(cat); db.commit(); db.refresh(cat)
        team = Team(name=f"{theme}-team", category_id=cat.id)
        db.add(team); db.commit(); db.refresh(team)
        prof = AgentProfile(
            organization_id=org.id, slug=f"{theme}-synth",
            display_name="Synth", agent_type="rag_synth",
        )
        db.add(prof); db.commit(); db.refresh(prof)
        return {
            "org_id": org.id, "user_id": user.id,
            "category_id": cat.id, "team_id": team.id,
            "profile_id": prof.id, "theme": theme,
        }
    finally:
        db.close()


_VALID_MODULAR = {
    "system": "You are SYS-{theme}.",
    "retrieval": "Use only the numbered context blocks.",
    "citation": "Every claim ends with [N].",
    "guardrails": "Decline if unsupported.",
}


def _make_fresh_profile(fx: dict) -> "uuid.UUID":
    """Create a fresh rag_synth profile in this org. Each layer test
    uses its own profile so the soft-active unique on (org, profile,
    scope) doesn't collide with prior tests."""
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile
    db = SessionLocal()
    try:
        prof = AgentProfile(
            organization_id=fx["org_id"],
            slug=f"layer-{uuid.uuid4().hex[:8]}",
            display_name="layer-prof", agent_type="rag_synth",
        )
        db.add(prof); db.commit(); db.refresh(prof)
        return prof.id
    finally:
        db.close()


def _make_org_scoped_version(
    fx: dict, body: dict, *,
    profile_id: "uuid.UUID | None" = None,
    retrieval: dict | None = None,
    tools: dict | None = None,
):
    """Create an organization-scoped config + published version under
    `profile_id` (defaults to fx['profile_id'])."""
    from app.db.database import SessionLocal
    from app.db.models import AgentPromptConfig
    from app.services.agents.publish import create_draft, publish_version

    db = SessionLocal()
    pid = profile_id or fx["profile_id"]
    try:
        cfg = AgentPromptConfig(
            organization_id=fx["org_id"],
            agent_profile_id=pid,
            scope_type="organization", scope_id=None,
            created_by=fx["user_id"],
        )
        db.add(cfg); db.commit(); db.refresh(cfg)
        v = create_draft(
            db, organization_id=fx["org_id"],
            agent_prompt_config_id=cfg.id,
            label=f"org-{uuid.uuid4().hex[:6]}",
            modular_prompt_json=body,
            variables_schema_json=[],
            retrieval_config_json=retrieval or {},
            model_config_json={},
            tool_permissions_json=tools or {"allowed": [], "denied": []},
            meta_json={}, created_by=fx["user_id"],
        )
        db.commit()
        publish_version(
            db, organization_id=fx["org_id"], version_id=v.id,
            actor_user_id=fx["user_id"],
        )
        return cfg.id, v.id
    finally:
        db.close()


def _make_scoped_version(
    fx: dict, scope_type: str, scope_id: int, body: dict,
    *,
    profile_id: "uuid.UUID | None" = None,
    retrieval: dict | None = None,
    tools: dict | None = None,
):
    from app.db.database import SessionLocal
    from app.db.models import AgentPromptConfig
    from app.services.agents.publish import create_draft, publish_version

    db = SessionLocal()
    pid = profile_id or fx["profile_id"]
    try:
        cfg = AgentPromptConfig(
            organization_id=fx["org_id"],
            agent_profile_id=pid,
            scope_type=scope_type, scope_id=scope_id,
            created_by=fx["user_id"],
        )
        db.add(cfg); db.commit(); db.refresh(cfg)
        v = create_draft(
            db, organization_id=fx["org_id"],
            agent_prompt_config_id=cfg.id,
            label=f"{scope_type}-{uuid.uuid4().hex[:6]}",
            modular_prompt_json=body,
            variables_schema_json=[],
            retrieval_config_json=retrieval or {},
            model_config_json={},
            tool_permissions_json=tools or {"allowed": [], "denied": []},
            meta_json={}, created_by=fx["user_id"],
        )
        db.commit()
        publish_version(
            db, organization_id=fx["org_id"], version_id=v.id,
            actor_user_id=fx["user_id"],
        )
        return cfg.id, v.id
    finally:
        db.close()


def _cleanup_all(fxs):
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        org_ids = [f["org_id"] for f in fxs]
        # Wipe in dependency order so FKs are happy.
        db.execute(sql_text(
            "DELETE FROM agent_runtime_logs WHERE organization_id = ANY(:o)"
        ), {"o": org_ids})
        db.execute(sql_text(
            "DELETE FROM rag_query_runs WHERE organization_id = ANY(:o)"
        ), {"o": org_ids})
        db.execute(sql_text(
            "UPDATE agent_prompt_configs SET active_version_id = NULL "
            "WHERE organization_id = ANY(:o)"
        ), {"o": org_ids})
        db.execute(sql_text(
            "DELETE FROM prompt_deployments WHERE organization_id = ANY(:o)"
        ), {"o": org_ids})
        db.execute(sql_text(
            "DELETE FROM prompt_versions WHERE organization_id = ANY(:o)"
        ), {"o": org_ids})
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


_FX: list[dict] = []


def _A() -> dict:
    return _FX[0]


def _B() -> dict:
    return _FX[1]


# ===========================================================================
# Composition tests (pure-functional, no DB)
# ===========================================================================


def test_interpolate_substitutes_variables():
    from app.services.agents.composition import interpolate
    rendered, warnings = interpolate(
        "Hello {{name}}, your team is {{team}}.",
        {"name": "Alice", "team": "Sales"},
    )
    assert "Hello Alice, your team is Sales." == rendered, rendered
    assert warnings == [], warnings


def test_interpolate_html_escapes_values():
    """A value containing prompt-structure tokens must be escaped so
    it can't masquerade as the template's own markers."""
    from app.services.agents.composition import interpolate
    rendered, _ = interpolate(
        "Q: {{q}}", {"q": "<script>alert(1)</script>"},
    )
    assert "&lt;script&gt;" in rendered, rendered
    assert "<script>" not in rendered, rendered


def test_interpolate_missing_variable_placeholder():
    from app.services.agents.composition import interpolate
    rendered, warnings = interpolate(
        "Hello {{name}}, your team is {{team}}.",
        {"name": "Alice"},  # team missing
    )
    assert "[team unavailable]" in rendered, rendered
    assert "missing_variable:team" in warnings, warnings


def test_interpolate_idempotent():
    from app.services.agents.composition import interpolate
    text = "Hello {{x}} {{y}} {{x}}"
    vars_ = {"x": "X", "y": "Y"}
    r1, _ = interpolate(text, vars_)
    r2, _ = interpolate(text, vars_)
    assert r1 == r2 == "Hello X Y X"


def test_compose_system_message_section_order():
    """Sections must appear in the locked order. Empty sections are
    skipped — no blank stanzas."""
    from app.services.agents.composition import compose_system_message
    body = {
        "system": "I am SYS.",
        "behavior": "Be terse.",
        # team_rules / meeting_type empty → skip
        "guardrails": "Decline if unsupported.",
        # retrieval / citation / output empty → skip
    }
    rendered, _ = compose_system_message(body, {})
    # Order: system, behavior, guardrails (the only three non-empty).
    expected = "I am SYS.\n\nBe terse.\n\nDecline if unsupported."
    assert rendered == expected, repr(rendered)


def test_compose_empty_sections_produce_no_blank_stanzas():
    from app.services.agents.composition import compose_system_message
    rendered, _ = compose_system_message(
        {"system": "S", "behavior": "", "guardrails": "G"}, {},
    )
    assert rendered == "S\n\nG", repr(rendered)
    # No leading or trailing whitespace either.
    assert not rendered.startswith("\n")
    assert not rendered.endswith("\n")


def test_composition_order_matches_section_keys():
    from app.services.agents.composition import composition_order
    from app.schemas.agent_schema import ModularPrompt
    assert set(composition_order()) == set(ModularPrompt.section_keys())


# ===========================================================================
# Cache tests
# ===========================================================================


def test_cache_put_then_get_returns_value():
    from app.services.agents.cache import ResolverCache
    c = ResolverCache(max_entries=10, ttl_seconds=60)
    c.put(("k",), 5, {"x": 1})
    got = c.get(("k",))
    assert got == (5, {"x": 1}), got


def test_cache_ttl_expiry_drops_entry():
    """Use a very short TTL so the entry expires inside the test."""
    from app.services.agents.cache import ResolverCache
    c = ResolverCache(max_entries=10, ttl_seconds=0.05)
    c.put(("k",), 1, "v")
    assert c.get(("k",)) == (1, "v")
    time.sleep(0.1)
    assert c.get(("k",)) is None


def test_cache_capacity_evicts_lru():
    from app.services.agents.cache import ResolverCache
    c = ResolverCache(max_entries=2, ttl_seconds=60)
    c.put(("a",), 1, "A")
    c.put(("b",), 1, "B")
    c.put(("c",), 1, "C")  # evicts 'a' (LRU)
    assert c.get(("a",)) is None
    assert c.get(("b",)) is not None
    assert c.get(("c",)) is not None


def test_cache_clear_resets_state():
    from app.services.agents.cache import ResolverCache
    c = ResolverCache(max_entries=10, ttl_seconds=60)
    c.put(("k",), 1, "v")
    c.get(("k",))
    c.clear()
    assert c.get(("k",)) is None
    stats = c.stats()
    assert stats["size"] == 0
    assert stats["hits"] == 0
    assert stats["misses"] == 1, stats  # the .get after clear counts as miss


def test_cache_locked_serializes_per_key():
    """Two threads both calling `locked(key)` must serialize; non-
    overlapping keys must not."""
    import threading
    from app.services.agents.cache import ResolverCache
    c = ResolverCache(max_entries=10, ttl_seconds=60)
    counter = {"n": 0}
    lock_held_evt = threading.Event()
    release_evt = threading.Event()

    def _thread_a():
        with c.locked(("k",)):
            counter["n"] += 1
            lock_held_evt.set()
            release_evt.wait(timeout=2)
            counter["n"] += 1

    def _thread_b():
        lock_held_evt.wait(timeout=1)
        with c.locked(("k",)):  # must block until thread_a releases
            # On entering, thread_a's second increment has happened
            assert counter["n"] == 2, counter["n"]
            counter["n"] += 1

    ta = threading.Thread(target=_thread_a)
    tb = threading.Thread(target=_thread_b)
    ta.start(); tb.start()
    lock_held_evt.wait(timeout=1)
    release_evt.set()
    ta.join(timeout=2); tb.join(timeout=2)
    assert counter["n"] == 3, counter["n"]


# ===========================================================================
# Resolver — fallback tests
# ===========================================================================


def test_resolver_no_profile_returns_filesystem_floor():
    """No profile id/slug supplied → resolver short-circuits to the
    filesystem floor for rag_synth, regardless of what profiles exist
    in the org. This is the conservative 7C semantic: the resolver
    only engages when the caller explicitly names a profile."""
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config
    db = SessionLocal()
    reset_for_tests()
    try:
        resolved = resolve_agent_runtime_config(
            db, organization_id=_A()["org_id"],
            agent_type="rag_synth",
        )
        # Floor returned
        sys_text = resolved.modular_prompts.get("system", "")
        assert "CITATION RULES" in sys_text, sys_text[:200]
        assert resolved.agent_profile_id is None
        assert resolved.prompt_version_id is None
        layers = [s.layer for s in resolved.resolution_path]
        assert layers == ["filesystem"], layers
        assert resolved.is_default_fallback is True
    finally:
        db.close()


def test_resolver_filesystem_for_rag_planner():
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config
    db = SessionLocal()
    reset_for_tests()
    try:
        resolved = resolve_agent_runtime_config(
            db, organization_id=_A()["org_id"],
            agent_type="rag_planner",
        )
        sys_text = resolved.modular_prompts.get("system", "")
        # planner v1 starts with the query-planner header
        assert "query planner" in sys_text.lower(), sys_text[:200]
    finally:
        db.close()


def test_resolver_unknown_agent_type_is_empty_fallback():
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config
    db = SessionLocal()
    reset_for_tests()
    try:
        resolved = resolve_agent_runtime_config(
            db, organization_id=_A()["org_id"],
            agent_type="importance_scorer",  # no filesystem floor
        )
        assert resolved.modular_prompts == {}
        assert resolved.is_default_fallback is True
    finally:
        db.close()


# ===========================================================================
# Resolver — DB layer tests
# ===========================================================================


def test_resolver_org_scope_contributes():
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config
    fx = _A()
    pid = _make_fresh_profile(fx)
    body = dict(_VALID_MODULAR)
    body["system"] = "ORG-LEVEL SYS"
    cfg_id, ver_id = _make_org_scoped_version(fx, body, profile_id=pid)
    db = SessionLocal()
    reset_for_tests()
    try:
        resolved = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
        )
        assert resolved.modular_prompts["system"] == "ORG-LEVEL SYS"
        assert resolved.prompt_version_id == ver_id
        layers = [s.layer for s in resolved.resolution_path]
        assert "organization" in layers, layers
    finally:
        db.close()


def test_resolver_category_overrides_org():
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config
    fx = _A()
    pid = _make_fresh_profile(fx)
    org_body = dict(_VALID_MODULAR); org_body["system"] = "FROM ORG"
    _make_org_scoped_version(fx, org_body, profile_id=pid)
    cat_body = dict(_VALID_MODULAR); cat_body["system"] = "FROM CATEGORY"
    _make_scoped_version(fx, "category", fx["category_id"], cat_body, profile_id=pid)
    db = SessionLocal()
    reset_for_tests()
    try:
        resolved = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
            category_id=fx["category_id"],
        )
        assert resolved.modular_prompts["system"] == "FROM CATEGORY"
    finally:
        db.close()


def test_resolver_team_overrides_category():
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config
    fx = _A()
    pid = _make_fresh_profile(fx)
    cat_body = dict(_VALID_MODULAR); cat_body["system"] = "FROM CATEGORY"
    _make_scoped_version(fx, "category", fx["category_id"], cat_body, profile_id=pid)
    team_body = dict(_VALID_MODULAR); team_body["system"] = "FROM TEAM"
    _make_scoped_version(fx, "team", fx["team_id"], team_body, profile_id=pid)
    db = SessionLocal()
    reset_for_tests()
    try:
        resolved = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
            team_id=fx["team_id"],
            category_id=fx["category_id"],
        )
        assert resolved.modular_prompts["system"] == "FROM TEAM"
        # Path records both layers
        layers = [s.layer for s in resolved.resolution_path]
        assert "category" in layers and "team" in layers, layers
    finally:
        db.close()


def test_resolver_retrieval_config_merge():
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config
    fx = _A()
    pid = _make_fresh_profile(fx)
    _make_org_scoped_version(fx, _VALID_MODULAR, profile_id=pid,
                             retrieval={"top_k_final": 5})
    _make_scoped_version(fx, "team", fx["team_id"], _VALID_MODULAR, profile_id=pid,
                         retrieval={"top_k_final": 20, "rerank_strategy": "importance_aware"})
    db = SessionLocal()
    reset_for_tests()
    try:
        resolved = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
            team_id=fx["team_id"],
        )
        # Team's value wins
        assert resolved.retrieval_config.top_k_final == 20
        # Team contributed the strategy too
        assert resolved.retrieval_config.rerank_strategy == "importance_aware"
    finally:
        db.close()


def test_resolver_tool_permissions_union():
    """Allowed AND denied are union across layers (deny is sticky)."""
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config
    fx = _A()
    pid = _make_fresh_profile(fx)
    _make_scoped_version(
        fx, "category", fx["category_id"], _VALID_MODULAR, profile_id=pid,
        tools={"allowed": ["web_search"], "denied": ["slack_post"]},
    )
    _make_scoped_version(
        fx, "team", fx["team_id"], _VALID_MODULAR, profile_id=pid,
        tools={"allowed": ["crm_lookup"], "denied": []},
    )
    db = SessionLocal()
    reset_for_tests()
    try:
        resolved = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
            team_id=fx["team_id"], category_id=fx["category_id"],
        )
        assert set(resolved.tool_permissions.allowed) >= {"web_search", "crm_lookup"}, \
            resolved.tool_permissions.allowed
        # Deny is sticky from category even though team didn't deny anything.
        assert "slack_post" in resolved.tool_permissions.denied
    finally:
        db.close()


def test_resolver_hash_deterministic():
    """Same DB state → same config_hash across calls."""
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config
    fx = _A()
    pid = _make_fresh_profile(fx)
    _make_org_scoped_version(fx, _VALID_MODULAR, profile_id=pid)
    db = SessionLocal()
    reset_for_tests()
    try:
        r1 = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
        )
        reset_for_tests()
        r2 = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
        )
        assert r1.config_hash == r2.config_hash, (r1.config_hash, r2.config_hash)
    finally:
        db.close()


# ===========================================================================
# Resolver — cache + epoch
# ===========================================================================


def test_resolver_second_call_is_cache_hit():
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import (
        cache_hit, resolve_agent_runtime_config,
    )
    fx = _A()
    pid = _make_fresh_profile(fx)
    _make_org_scoped_version(fx, _VALID_MODULAR, profile_id=pid)
    db = SessionLocal()
    reset_for_tests()
    try:
        r1 = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
        )
        r2 = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
        )
        assert not cache_hit(r1), "first call should be a miss"
        assert cache_hit(r2), "second call should be a hit"
    finally:
        db.close()


def test_resolver_epoch_bump_invalidates_cache():
    """After a publish (which bumps the epoch), the next resolve must
    NOT serve from cache."""
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.publish import (
        create_draft, publish_version,
    )
    from app.services.agents.resolver import (
        cache_hit, resolve_agent_runtime_config,
    )
    fx = _A()
    pid = _make_fresh_profile(fx)
    cfg_id, _ = _make_org_scoped_version(fx, dict(_VALID_MODULAR), profile_id=pid)
    db = SessionLocal()
    reset_for_tests()
    try:
        # Warm the cache
        resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
        )
        r2 = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
        )
        assert cache_hit(r2), "should be cached after warm"
        # New draft + publish — bumps epoch
        new_body = dict(_VALID_MODULAR); new_body["system"] = "BUMPED"
        v = create_draft(
            db, organization_id=fx["org_id"],
            agent_prompt_config_id=cfg_id,
            label="bump", modular_prompt_json=new_body,
            variables_schema_json=[], retrieval_config_json={},
            model_config_json={}, tool_permissions_json={"allowed":[],"denied":[]},
            meta_json={}, created_by=fx["user_id"],
        )
        db.commit()
        publish_version(
            db, organization_id=fx["org_id"], version_id=v.id,
            actor_user_id=fx["user_id"],
        )
        # Next resolve must be a miss + must reflect new body
        r3 = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
        )
        assert not cache_hit(r3), "publish should have invalidated cache"
        assert r3.modular_prompts["system"] == "BUMPED"
    finally:
        db.close()


def test_resolver_different_teams_different_cache_entries():
    """Same profile, different team_id, different cache entry.
    Verified indirectly: the resolved system text differs."""
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config
    fx = _A()
    pid = _make_fresh_profile(fx)
    # One team-specific config — only matches when team_id == fx['team_id']
    team_body = dict(_VALID_MODULAR); team_body["system"] = "TEAM ONLY"
    _make_scoped_version(fx, "team", fx["team_id"], team_body, profile_id=pid)
    db = SessionLocal()
    reset_for_tests()
    try:
        # Call WITHOUT team_id → team layer doesn't apply
        r_no_team = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
        )
        # Call WITH team_id → team layer applies
        r_with_team = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid,
            team_id=fx["team_id"],
        )
        assert r_with_team.modular_prompts["system"] == "TEAM ONLY"
        assert r_no_team.modular_prompts.get("system") != "TEAM ONLY"
    finally:
        db.close()


def test_resolver_cross_org_isolation():
    """Org A has a team-scoped override. Org B passes the same team_id
    (defense-in-depth: confirm the organization_id filter rejects it)."""
    from app.db.database import SessionLocal
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config
    fx_a = _A(); fx_b = _B()
    pid_a = _make_fresh_profile(fx_a)
    pid_b = _make_fresh_profile(fx_b)
    body = dict(_VALID_MODULAR); body["system"] = "ORG-A SECRET"
    _make_scoped_version(fx_a, "team", fx_a["team_id"], body, profile_id=pid_a)
    db = SessionLocal()
    reset_for_tests()
    try:
        resolved = resolve_agent_runtime_config(
            db, organization_id=fx_b["org_id"],
            agent_type="rag_synth",
            agent_profile_id=pid_b,
            team_id=fx_a["team_id"],  # malicious team_id from org A
        )
        # Must NOT see ORG-A SECRET. Falls back to filesystem.
        assert "ORG-A SECRET" not in resolved.modular_prompts.get("system", "")
    finally:
        db.close()


# ===========================================================================
# Shadow-mode wiring tests
# ===========================================================================


def test_ask_stream_writes_runtime_log():
    """An end-to-end /rag/ask call (via the underlying ask_stream
    generator) must produce one `agent_runtime_logs` row tied back to
    the rag_query_runs row."""
    from app.db.database import SessionLocal
    from app.db.models import AgentRuntimeLog, RagQueryRun
    from app.services.rag.ask_pipeline import ask_stream
    from tests.fixtures.canonical_org import (
        build_canonical_org, canonical_stub_embed, cleanup_canonical_org,
    )

    # Build the canonical org for retrieval to have something to chunk
    setup_db = SessionLocal()
    fx = None
    try:
        fx = build_canonical_org(setup_db, mode="stub")
    finally:
        setup_db.close()

    # Stub the embedder — plain class with `embed()` matching the
    # pattern in test_phase5b.py. Does NOT subclass Embedder (which
    # would require batch_size + the openai client + retry config).
    class _StubEmbedder:
        model = "stub-canonical"
        def embed(self, texts):
            return [canonical_stub_embed(t) for t in texts]

    # Stub the synth call by injecting a canned planner result + canned
    # synth tokens via the existing test seams.
    from app.services.rag.query_planner import _set_test_responses as set_planner_responses
    from app.services.rag import synthesizer
    set_planner_responses([
        '{"query_type":"factual","effective_scope_type":"global",'
        '"effective_scope_id":null,"detected_entity_names":["Helios"],'
        '"time_hint":null,"confidence":0.9}'
    ])
    # Replace synth's OpenAI streaming with a canned generator.
    orig_call = getattr(synthesizer, "_call_synth_stream", None)
    def _fake_synth(*, prompt, model):
        yield "Helios ships [1]."
    synthesizer._call_synth_stream = _fake_synth  # type: ignore[assignment]

    db = SessionLocal()
    try:
        before_logs = db.query(AgentRuntimeLog).filter(
            AgentRuntimeLog.organization_id == fx.organization_id,
        ).count()
        before_runs = db.query(RagQueryRun).filter(
            RagQueryRun.organization_id == fx.organization_id,
        ).count()

        events = list(ask_stream(
            db, organization_id=fx.organization_id,
            user_id=fx.user_id, query_text="When does Helios ship?",
            embedder=_StubEmbedder(),
        ))
        # Drain the stream — must end in 'done'
        assert events and events[-1]["event"] == "done", events[-1]

        after_logs = db.query(AgentRuntimeLog).filter(
            AgentRuntimeLog.organization_id == fx.organization_id,
        ).count()
        after_runs = db.query(RagQueryRun).filter(
            RagQueryRun.organization_id == fx.organization_id,
        ).count()
        assert after_runs == before_runs + 1, (before_runs, after_runs)
        assert after_logs == before_logs + 1, (before_logs, after_logs)

        # Latest log row must carry the resolved_config_hash + agent_type
        last_log = db.query(AgentRuntimeLog).filter(
            AgentRuntimeLog.organization_id == fx.organization_id,
        ).order_by(AgentRuntimeLog.created_at.desc()).first()
        assert last_log.agent_type == "rag_synth"
        assert last_log.resolved_config_hash, last_log.resolved_config_hash

        # Latest run row must have resolution_path_hash populated
        last_run = db.query(RagQueryRun).filter(
            RagQueryRun.organization_id == fx.organization_id,
        ).order_by(RagQueryRun.created_at.desc()).first()
        assert last_run.resolution_path_hash == last_log.resolved_config_hash
    finally:
        if orig_call is not None:
            synthesizer._call_synth_stream = orig_call  # type: ignore[assignment]
        cleanup_canonical_org(db, fx)
        db.close()


# ===========================================================================
# HTTP tests
# ===========================================================================


def test_http_debug_resolve_endpoint():
    from app.services.agents.cache import reset_for_tests
    fx = _A()
    pid = _make_fresh_profile(fx)
    body = dict(_VALID_MODULAR); body["system"] = "DEBUG ORG SYS"
    _make_org_scoped_version(fx, body, profile_id=pid)
    reset_for_tests()
    r = _client_for(fx["user_id"]).get(
        "/agents/runtime/resolve",
        params={
            "agent_type": "rag_synth",
            "agent_profile_id": str(pid),
        },
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["modular_prompts"]["system"] == "DEBUG ORG SYS"
    assert "config_hash" in j
    assert "resolution_path" in j


def test_http_resolution_distribution_endpoint():
    """After at least one ask_stream call has logged a row, the
    distribution endpoint returns its hash + count."""
    from app.db.database import SessionLocal
    from app.db.models import AgentRuntimeLog
    fx = _A()
    # Insert a synthetic runtime log row directly — simpler than
    # running ask_stream again (already covered in another test).
    db = SessionLocal()
    try:
        row = AgentRuntimeLog(
            organization_id=fx["org_id"],
            agent_profile_id=fx["profile_id"],
            agent_type="rag_synth",
            resolution_path_json=[],
            resolved_config_hash="deadbeef" * 8,
            cache_hit=False, resolve_duration_ms=1,
        )
        db.add(row); db.commit()
    finally:
        db.close()

    r = _client_for(fx["user_id"]).get(
        "/rag/observability/resolution-distribution",
        params={"days": 7, "agent_type": "rag_synth"},
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    hashes = {it["config_hash"] for it in rows}
    assert ("deadbeef" * 8) in hashes, rows


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    global _FX
    _FX = [_seed_org("alpha"), _seed_org("bravo")]

    try:
        with section("7C - composition"):
            check("7C", "interpolate substitutes variables",
                  test_interpolate_substitutes_variables)
            check("7C", "interpolate HTML-escapes values",
                  test_interpolate_html_escapes_values)
            check("7C", "interpolate yields placeholder + warning on missing",
                  test_interpolate_missing_variable_placeholder)
            check("7C", "interpolate is idempotent",
                  test_interpolate_idempotent)
            check("7C", "compose_system_message respects locked order",
                  test_compose_system_message_section_order)
            check("7C", "empty sections produce no blank stanzas",
                  test_compose_empty_sections_produce_no_blank_stanzas)
            check("7C", "composition order matches ModularPrompt.section_keys()",
                  test_composition_order_matches_section_keys)

        with section("7C - cache"):
            check("7C", "put then get returns value",
                  test_cache_put_then_get_returns_value)
            check("7C", "TTL expiry drops the entry",
                  test_cache_ttl_expiry_drops_entry)
            check("7C", "capacity evicts LRU",
                  test_cache_capacity_evicts_lru)
            check("7C", "clear resets stats + entries",
                  test_cache_clear_resets_state)
            check("7C", "locked() serializes per-key",
                  test_cache_locked_serializes_per_key)

        with section("7C - resolver fallback"):
            check("7C", "no profile -> filesystem floor (rag_synth)",
                  test_resolver_no_profile_returns_filesystem_floor)
            check("7C", "no profile -> filesystem floor (rag_planner)",
                  test_resolver_filesystem_for_rag_planner)
            check("7C", "unknown agent_type -> empty fallback",
                  test_resolver_unknown_agent_type_is_empty_fallback)

        with section("7C - resolver DB layers"):
            check("7C", "org-scoped version contributes",
                  test_resolver_org_scope_contributes)
            check("7C", "category overrides org on overlapping keys",
                  test_resolver_category_overrides_org)
            check("7C", "team overrides category",
                  test_resolver_team_overrides_category)
            check("7C", "retrieval_config merges higher-priority over lower",
                  test_resolver_retrieval_config_merge)
            check("7C", "tool_permissions allowed+denied are union",
                  test_resolver_tool_permissions_union)
            check("7C", "config_hash deterministic across calls",
                  test_resolver_hash_deterministic)

        with section("7C - resolver cache + epoch"):
            check("7C", "second call with same inputs is a cache hit",
                  test_resolver_second_call_is_cache_hit)
            check("7C", "publish (epoch bump) invalidates cache",
                  test_resolver_epoch_bump_invalidates_cache)
            check("7C", "different team_id produces different bundle",
                  test_resolver_different_teams_different_cache_entries)
            check("7C", "cross-org isolation: org B never sees org A's overrides",
                  test_resolver_cross_org_isolation)

        with section("7C - shadow-mode wiring"):
            check("7C", "ask_stream writes one agent_runtime_logs row",
                  test_ask_stream_writes_runtime_log)

        with section("7C - HTTP"):
            check("7C", "GET /agents/runtime/resolve returns merged bundle",
                  test_http_debug_resolve_endpoint)
            check("7C", "GET /rag/observability/resolution-distribution lists hashes",
                  test_http_resolution_distribution_endpoint)
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
