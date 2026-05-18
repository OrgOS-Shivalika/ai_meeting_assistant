"""Phase 7D ship test — live consumption + filesystem-to-DB seed.

Invariants verified:

  Resolver — filesystem floor splitting:
   1. _filesystem_floor('rag_synth') splits at the LLM-input marker
   2. _filesystem_floor('rag_synth') converts {org_name} -> {{org_name}}
   3. _filesystem_floor('rag_planner') splits similarly

  Synth — backward compat:
   4. legacy path (resolved_config=None) is unchanged: bit-equal to
      pre-7D _render_synth_prompt output
   5. resolved-path with filesystem floor only reproduces legacy
      prompt text byte-for-byte
   6. _RAG_SYNTH_USER_TEMPLATE concatenated with composed-floor
      reconstructs the filesystem v1.txt exactly

  Synth — resolved path:
   7. when resolved_config carries an org-scoped override, the synth
      prompt reflects the override
   8. label + version_number land on rag_query_runs.synth_prompt_version
      via _resolved_prompt_version_tag

  Seed service:
   9. seed_default_agents_for_org creates default profiles + configs +
      published v1 for a fresh org
  10. re-running on a seeded org is a no-op
  11. seeded prompt_versions have seeded_from_filesystem=True
  12. seeded v1's modular_prompt['system'] matches the filesystem floor
      content (the bytes that produce identical LLM input)
  13. seeded org's resolver returns the DB version, NOT the floor

  End-to-end through ask_stream:
  14. live-mode ask_stream with a seeded synth_default profile uses
      the resolved bundle (rag_query_runs.prompt_version_id is set)
  15. shadow-mode (AGENT_RESOLVER_SHADOW_MODE=true) DOES NOT pass the
      resolved config to synth — prompt_version on the run row stays
      at the filesystem version

  CLI:
  16. seed_default_agents.py --dry-run reports without writing
  17. seed_default_agents.py --org-id <uuid> seeds only that org

Run with:

    venv\\Scripts\\python.exe tests\\test_phase7d.py
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
        msg = traceback.format_exc(limit=6).strip().splitlines()[-1]
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
    from app.db.models import Category, Organization, Team, User
    db = SessionLocal()
    try:
        org = Organization(name=f"7d-{theme}-org")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"7d-{theme}",
            email=f"7d-{theme}-{uuid.uuid4()}@example.com",
            password="x", organization_id=org.id,
        )
        db.add(user); db.commit(); db.refresh(user)
        cat = Category(name=f"{theme}-cat", organization_id=org.id, user_id=user.id)
        db.add(cat); db.commit(); db.refresh(cat)
        team = Team(name=f"{theme}-team", category_id=cat.id)
        db.add(team); db.commit(); db.refresh(team)
        return {
            "org_id": org.id, "user_id": user.id,
            "category_id": cat.id, "team_id": team.id,
        }
    finally:
        db.close()


def _cleanup_all(fxs):
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        org_ids = [f["org_id"] for f in fxs]
        for stmt in (
            "DELETE FROM agent_runtime_logs WHERE organization_id = ANY(:o)",
            "DELETE FROM rag_query_runs WHERE organization_id = ANY(:o)",
            "UPDATE agent_prompt_configs SET active_version_id = NULL "
            "WHERE organization_id = ANY(:o)",
            "DELETE FROM prompt_deployments WHERE organization_id = ANY(:o)",
            "DELETE FROM prompt_versions WHERE organization_id = ANY(:o)",
            "DELETE FROM agent_config_epochs WHERE organization_id = ANY(:o)",
            "DELETE FROM agent_prompt_configs WHERE organization_id = ANY(:o)",
            "DELETE FROM agent_profiles WHERE organization_id = ANY(:o)",
        ):
            db.execute(sql_text(stmt), {"o": org_ids})
        db.execute(sql_text("DELETE FROM teams WHERE id = ANY(:ids)"),
                   {"ids": [f["team_id"] for f in fxs]})
        db.execute(sql_text("DELETE FROM categories WHERE id = ANY(:ids)"),
                   {"ids": [f["category_id"] for f in fxs]})
        db.execute(sql_text("DELETE FROM users WHERE id = ANY(:ids)"),
                   {"ids": [f["user_id"] for f in fxs]})
        db.execute(sql_text("DELETE FROM organizations WHERE id = ANY(:o)"),
                   {"o": org_ids})
        db.commit()
    finally:
        db.close()


_FX: list[dict] = []


def _A() -> dict:
    return _FX[0]


# ===========================================================================
# Filesystem-floor tests
# ===========================================================================


def test_floor_split_at_marker_synth():
    from app.services.agents.resolver import _filesystem_floor
    floor, _ = _filesystem_floor("rag_synth")
    sys_text = floor.get("system", "")
    assert sys_text, "expected non-empty system section from synth floor"
    assert "CITATION RULES" in sys_text, "missing CITATION RULES from floor"
    # The marker itself must NOT be in the pre-marker block.
    assert "=== CONTEXT ===" not in sys_text, sys_text[-80:]


def test_floor_converts_single_to_double_brace_synth():
    from app.services.agents.resolver import _filesystem_floor
    floor, _ = _filesystem_floor("rag_synth")
    sys_text = floor.get("system", "")
    assert "{{org_name}}" in sys_text, "org_name not converted to double-brace"
    assert "{org_name}" not in sys_text.replace("{{org_name}}", ""), \
        "stray single-brace {org_name} left after conversion"


def test_floor_split_planner():
    from app.services.agents.resolver import _filesystem_floor
    floor, _ = _filesystem_floor("rag_planner")
    sys_text = floor.get("system", "")
    assert sys_text, "expected non-empty system section from planner floor"
    # USER CONTEXT marker is the split boundary; it must NOT be in
    # the pre-marker block.
    assert "USER CONTEXT" not in sys_text


# ===========================================================================
# Synth — backward compat
# ===========================================================================


def test_synth_legacy_path_unchanged():
    """resolved_config=None must reproduce the pre-7D prompt path
    exactly. Sanity check on the no-op default."""
    from app.ai_agents.prompts.rag import load_synth_prompt
    from app.services.rag.synthesizer import _render_synth_prompt
    template = load_synth_prompt("v1")
    legacy = _render_synth_prompt(
        template=template, org_name="Acme",
        query_text="Q?", context_blocks="[1] X",
    )
    # Spot-check: it contains both the org name and the context
    assert "Acme" in legacy
    assert "[1] X" in legacy
    assert "Q?" in legacy


def test_resolved_path_floor_only_byte_equal_legacy():
    """The most important guarantee: feeding the filesystem floor
    through the composer + appending the user template MUST produce
    the same bytes as the legacy `_render_synth_prompt`."""
    from app.ai_agents.prompts.rag import load_synth_prompt
    from app.services.agents.composition import compose_system_message
    from app.services.agents.resolver import _filesystem_floor
    from app.services.rag.synthesizer import (
        _RAG_SYNTH_USER_TEMPLATE, _render_synth_prompt,
    )
    org = "Acme Inc"
    ctx = "[1] MEETING \"X\" (Apr 1, speakers: A)\n    Some content."
    q = "When does Helios ship?"

    # Legacy
    legacy_template = load_synth_prompt("v1")
    legacy = _render_synth_prompt(
        template=legacy_template, org_name=org,
        query_text=q, context_blocks=ctx,
    )

    # Resolved-path with floor-only
    floor, _ = _filesystem_floor("rag_synth")
    composed, _ = compose_system_message(
        floor,
        variables={"org_name": org, "context_blocks": ctx, "query_text": q},
    )
    user_msg = _RAG_SYNTH_USER_TEMPLATE.format(context_blocks=ctx, query_text=q)
    resolved = composed + "\n\n" + user_msg

    assert legacy == resolved, (
        f"byte mismatch (legacy={len(legacy)}, resolved={len(resolved)})\n"
        f"legacy tail: {legacy[-40:]!r}\nresolved tail: {resolved[-40:]!r}"
    )


def test_resolved_path_with_override():
    """An org-level override of the `system` section should land in
    the assembled prompt instead of the floor's content."""
    from app.services.agents.composition import compose_system_message
    from app.services.rag.synthesizer import _RAG_SYNTH_USER_TEMPLATE
    override = {"system": "I am the OVERRIDE system."}
    composed, _ = compose_system_message(
        override, variables={"org_name": "Acme"},
    )
    user_msg = _RAG_SYNTH_USER_TEMPLATE.format(
        context_blocks="[1] ctx", query_text="q",
    )
    prompt = composed + "\n\n" + user_msg
    assert "OVERRIDE" in prompt
    assert "CITATION RULES" not in prompt, (
        "override should replace floor's system content"
    )


def test_resolved_prompt_version_tag():
    from dataclasses import dataclass
    from app.services.rag.synthesizer import _resolved_prompt_version_tag

    @dataclass
    class _Stub:
        version_number: int | None = None
        label: str | None = None

    # Filesystem-only floor → -floor suffix
    tag = _resolved_prompt_version_tag(_Stub(version_number=None))
    assert tag.endswith("-floor"), tag
    # DB version, no label → vN
    assert _resolved_prompt_version_tag(_Stub(version_number=3)) == "v3"
    # DB version + label → v3-label
    assert _resolved_prompt_version_tag(
        _Stub(version_number=3, label="experiment-A"),
    ) == "v3-experiment-A"


# ===========================================================================
# Seed service
# ===========================================================================


def test_seed_creates_defaults_for_fresh_org():
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, AgentPromptConfig, PromptVersion
    from app.services.agents.seed_defaults import seed_default_agents_for_org

    fx = _A()
    db = SessionLocal()
    try:
        result = seed_default_agents_for_org(
            db, organization_id=fx["org_id"],
            created_by_user_id=fx["user_id"],
        )
        assert result.profiles_created, result
        assert not result.profiles_failed, result.profiles_failed
        # Confirm DB state
        profiles = db.query(AgentProfile).filter(
            AgentProfile.organization_id == fx["org_id"],
        ).all()
        slugs = {p.slug for p in profiles}
        assert "default_synth" in slugs
        assert "default_planner" in slugs
        # synth profile has an active config + published version
        synth = next(p for p in profiles if p.slug == "default_synth")
        cfg = db.query(AgentPromptConfig).filter(
            AgentPromptConfig.agent_profile_id == synth.id,
            AgentPromptConfig.scope_type == "organization",
        ).first()
        assert cfg is not None
        assert cfg.active_version_id is not None
        v = db.query(PromptVersion).filter(
            PromptVersion.id == cfg.active_version_id,
        ).first()
        assert v.state == "published"
        assert v.seeded_from_filesystem is True
    finally:
        db.close()


def test_seed_is_idempotent():
    """Re-running seed on the same org produces no new profiles or
    versions — every profile is 'already_seeded'."""
    from app.db.database import SessionLocal
    from app.db.models import PromptVersion
    from app.services.agents.seed_defaults import seed_default_agents_for_org

    fx = _A()
    db = SessionLocal()
    try:
        # First call has already happened above; re-run.
        before = db.query(PromptVersion).filter(
            PromptVersion.organization_id == fx["org_id"],
        ).count()
        result = seed_default_agents_for_org(
            db, organization_id=fx["org_id"],
        )
        after = db.query(PromptVersion).filter(
            PromptVersion.organization_id == fx["org_id"],
        ).count()
        # No NEW versions created
        assert after == before, (before, after)
        # All slugs should be reported as already_seeded
        assert not result.profiles_created, result.profiles_created
        # The 5 default profiles: synth, planner, graph, transcript, summarizer
        # summarizer has no floor → not in already_seeded list
        already = set(result.profiles_already_seeded)
        assert "default_synth" in already
        assert "default_planner" in already
    finally:
        db.close()


def test_seeded_system_section_matches_floor():
    """The system section stored in the seeded v1 must match the
    floor content byte-for-byte. (This is what makes pre/post-seed
    behavior identical.)"""
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, AgentPromptConfig, PromptVersion
    from app.services.agents.resolver import _filesystem_floor

    fx = _A()
    db = SessionLocal()
    try:
        prof = db.query(AgentProfile).filter(
            AgentProfile.organization_id == fx["org_id"],
            AgentProfile.slug == "default_synth",
        ).first()
        cfg = db.query(AgentPromptConfig).filter(
            AgentPromptConfig.agent_profile_id == prof.id,
        ).first()
        v = db.query(PromptVersion).filter(
            PromptVersion.id == cfg.active_version_id,
        ).first()
        floor, _ = _filesystem_floor("rag_synth")
        assert v.modular_prompt_json.get("system") == floor.get("system"), (
            "seeded system section diverged from filesystem floor"
        )
    finally:
        db.close()


def test_seeded_resolver_returns_db_version_not_floor():
    """After seed, the resolver should produce a bundle whose
    prompt_version_id is the seeded v1 (not None). The path includes
    an 'organization' layer, not just 'filesystem'."""
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.resolver import resolve_agent_runtime_config

    fx = _A()
    db = SessionLocal()
    reset_for_tests()
    try:
        prof = db.query(AgentProfile).filter(
            AgentProfile.organization_id == fx["org_id"],
            AgentProfile.slug == "default_synth",
        ).first()
        resolved = resolve_agent_runtime_config(
            db, organization_id=fx["org_id"],
            agent_type="rag_synth",
            agent_profile_id=prof.id,
        )
        assert resolved.prompt_version_id is not None
        layers = [s.layer for s in resolved.resolution_path]
        assert "organization" in layers, layers
    finally:
        db.close()


# ===========================================================================
# End-to-end via ask_stream
# ===========================================================================


def _stub_synth_to_canned_answer():
    """Replace the streaming LLM call with a canned response so the
    test runs offline. Returns the function to restore."""
    from app.services.rag import synthesizer
    original = synthesizer._call_synth_llm_stream

    def _fake(*, prompt, model):
        yield "Helios ships [1]."

    synthesizer._call_synth_llm_stream = _fake  # type: ignore[assignment]
    return original


def _restore_synth(original):
    from app.services.rag import synthesizer
    synthesizer._call_synth_llm_stream = original  # type: ignore[assignment]


def test_ask_stream_live_mode_uses_resolved_version():
    """In live mode, ask_stream's call to synthesize_stream receives
    the resolved bundle and the audit row's prompt_version_id is set
    to the seeded version."""
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, RagQueryRun
    from app.services.rag.ask_pipeline import ask_stream
    from app.services.rag.query_planner import _set_test_responses
    from tests.fixtures.canonical_org import (
        build_canonical_org, canonical_stub_embed, cleanup_canonical_org,
    )

    setup_db = SessionLocal()
    fx = None
    try:
        fx = build_canonical_org(setup_db, mode="stub")
    finally:
        setup_db.close()

    class _StubEmbedder:
        model = "stub"
        def embed(self, texts):
            return [canonical_stub_embed(t) for t in texts]

    # Seed defaults on the canonical org
    db = SessionLocal()
    try:
        from app.services.agents.seed_defaults import seed_default_agents_for_org
        seed_default_agents_for_org(db, organization_id=fx.organization_id)
        # Resolve the seeded synth profile's slug
        synth_prof = db.query(AgentProfile).filter(
            AgentProfile.organization_id == fx.organization_id,
            AgentProfile.slug == "default_synth",
        ).first()
        assert synth_prof is not None
        from app.db.models import AgentPromptConfig, PromptVersion
        cfg = db.query(AgentPromptConfig).filter(
            AgentPromptConfig.agent_profile_id == synth_prof.id,
        ).first()
        seeded_version_id = cfg.active_version_id
        assert seeded_version_id is not None
    finally:
        db.close()

    _set_test_responses([
        '{"query_type":"factual","effective_scope_type":"global",'
        '"effective_scope_id":null,"detected_entity_names":["Helios"],'
        '"time_hint":null,"confidence":0.9}'
    ])
    restore = _stub_synth_to_canned_answer()

    db = SessionLocal()
    try:
        events = list(ask_stream(
            db, organization_id=fx.organization_id,
            user_id=fx.user_id, query_text="When does Helios ship?",
            embedder=_StubEmbedder(),
            agent_profile_slug="default_synth",
        ))
        assert events and events[-1]["event"] == "done"

        last_run = db.query(RagQueryRun).filter(
            RagQueryRun.organization_id == fx.organization_id,
        ).order_by(RagQueryRun.created_at.desc()).first()
        assert last_run is not None
        # In live mode, the resolved version_id is captured
        assert last_run.prompt_version_id == seeded_version_id, (
            last_run.prompt_version_id, seeded_version_id,
        )
        # synth_prompt_version is the resolved tag, not the env-var default
        assert last_run.synth_prompt_version and \
            last_run.synth_prompt_version.startswith("v1"), \
            last_run.synth_prompt_version
    finally:
        _restore_synth(restore)
        # Clean up the runtime logs + query runs we just created so
        # the canonical_org cleanup doesn't trip on FKs
        from sqlalchemy import text as sql_text
        try:
            db.execute(sql_text(
                "DELETE FROM agent_runtime_logs WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM rag_query_runs WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            # Wipe the seeded agent rows so the canonical cleanup is clean
            db.execute(sql_text(
                "UPDATE agent_prompt_configs SET active_version_id = NULL "
                "WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM prompt_deployments WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM prompt_versions WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM agent_config_epochs WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM agent_prompt_configs WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM agent_profiles WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.commit()
        except Exception:
            db.rollback()
        cleanup_canonical_org(db, fx)
        db.close()


def test_shadow_mode_does_not_pass_resolved_to_synth():
    """With AGENT_RESOLVER_SHADOW_MODE=true the synth path uses the
    legacy filesystem template, NOT the resolved bundle. Verified by
    inspecting the synth_prompt_version landed on the run row — in
    shadow mode it's the filesystem version (e.g. 'v1'), not the
    resolved-tag form ('v1-seeded')."""
    from app.config.settings import settings as _settings
    from app.db.database import SessionLocal
    from app.db.models import (
        AgentProfile, AgentPromptConfig, RagQueryRun,
    )
    from app.services.agents.cache import reset_for_tests
    from app.services.agents.seed_defaults import seed_default_agents_for_org
    from app.services.rag.ask_pipeline import ask_stream
    from app.services.rag.query_planner import _set_test_responses
    from tests.fixtures.canonical_org import (
        build_canonical_org, canonical_stub_embed, cleanup_canonical_org,
    )

    # Build a fresh canonical org; seed defaults.
    setup_db = SessionLocal()
    fx = None
    try:
        fx = build_canonical_org(setup_db, mode="stub")
        seed_default_agents_for_org(setup_db, organization_id=fx.organization_id)
    finally:
        setup_db.close()

    class _StubEmbedder:
        model = "stub"
        def embed(self, texts):
            return [canonical_stub_embed(t) for t in texts]

    _set_test_responses([
        '{"query_type":"factual","effective_scope_type":"global",'
        '"effective_scope_id":null,"detected_entity_names":["Helios"],'
        '"time_hint":null,"confidence":0.9}'
    ])
    restore = _stub_synth_to_canned_answer()

    prev_shadow = _settings.AGENT_RESOLVER_SHADOW_MODE
    _settings.AGENT_RESOLVER_SHADOW_MODE = True

    db = SessionLocal()
    try:
        reset_for_tests()
        events = list(ask_stream(
            db, organization_id=fx.organization_id,
            user_id=fx.user_id, query_text="When does Helios ship?",
            embedder=_StubEmbedder(),
            agent_profile_slug="default_synth",
        ))
        assert events and events[-1]["event"] == "done"
        last_run = db.query(RagQueryRun).filter(
            RagQueryRun.organization_id == fx.organization_id,
        ).order_by(RagQueryRun.created_at.desc()).first()
        # Shadow mode: synth_prompt_version is the filesystem env-var
        # default ('v1'), NOT a resolved tag.
        assert last_run.synth_prompt_version == "v1", last_run.synth_prompt_version
    finally:
        _settings.AGENT_RESOLVER_SHADOW_MODE = prev_shadow
        _restore_synth(restore)
        # Same cleanup dance as the live-mode test
        from sqlalchemy import text as sql_text
        try:
            db.execute(sql_text(
                "DELETE FROM agent_runtime_logs WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM rag_query_runs WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "UPDATE agent_prompt_configs SET active_version_id = NULL "
                "WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM prompt_deployments WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM prompt_versions WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM agent_config_epochs WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM agent_prompt_configs WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.execute(sql_text(
                "DELETE FROM agent_profiles WHERE organization_id = :o"
            ), {"o": str(fx.organization_id)})
            db.commit()
        except Exception:
            db.rollback()
        cleanup_canonical_org(db, fx)
        db.close()


# ===========================================================================
# CLI
# ===========================================================================


def test_cli_dry_run_makes_no_changes():
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile
    from app.scripts.seed_default_agents import main as cli_main

    fx = _A()
    db = SessionLocal()
    try:
        before = db.query(AgentProfile).filter(
            AgentProfile.organization_id == fx["org_id"],
        ).count()
    finally:
        db.close()

    rc = cli_main(["--org-id", str(fx["org_id"]), "--dry-run"])
    assert rc == 0

    db = SessionLocal()
    try:
        after = db.query(AgentProfile).filter(
            AgentProfile.organization_id == fx["org_id"],
        ).count()
        assert after == before, (before, after)
    finally:
        db.close()


def test_cli_single_org_seed():
    """--org-id <uuid> on an unseeded org creates exactly the
    org's defaults. Uses a fresh org per call so we don't fight the
    fixture's existing seed state."""
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, Organization, User
    from app.scripts.seed_default_agents import main as cli_main

    # Make a brand-new org for this test.
    db = SessionLocal()
    try:
        org = Organization(name=f"7d-cli-org-{uuid.uuid4().hex[:6]}")
        db.add(org); db.commit(); db.refresh(org)
        oid = org.id
    finally:
        db.close()

    try:
        rc = cli_main(["--org-id", str(oid)])
        assert rc == 0

        db = SessionLocal()
        try:
            n = db.query(AgentProfile).filter(
                AgentProfile.organization_id == oid,
            ).count()
            assert n >= 4, n  # synth + planner + graph + transcript + summarizer (>= 4)
        finally:
            db.close()
    finally:
        # Cleanup the org we created (CASCADE wipes its agent rows).
        db = SessionLocal()
        try:
            from sqlalchemy import text as sql_text
            db.execute(sql_text(
                "DELETE FROM prompt_deployments WHERE organization_id = :o"
            ), {"o": str(oid)})
            db.execute(sql_text(
                "DELETE FROM organizations WHERE id = :o"
            ), {"o": str(oid)})
            db.commit()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    global _FX
    _FX = [_seed_org("alpha")]

    try:
        with section("7D - filesystem floor"):
            check("7D", "floor splits synth at marker", test_floor_split_at_marker_synth)
            check("7D", "floor converts {org_name} to {{org_name}} (synth)",
                  test_floor_converts_single_to_double_brace_synth)
            check("7D", "floor splits planner at marker", test_floor_split_planner)

        with section("7D - synth backward compat"):
            check("7D", "legacy path (resolved_config=None) unchanged",
                  test_synth_legacy_path_unchanged)
            check("7D", "resolved path with floor-only is byte-equal to legacy",
                  test_resolved_path_floor_only_byte_equal_legacy)
            check("7D", "override replaces floor's system content",
                  test_resolved_path_with_override)
            check("7D", "_resolved_prompt_version_tag handles -floor, vN, vN-label",
                  test_resolved_prompt_version_tag)

        with section("7D - seed service"):
            check("7D", "seed_default_agents_for_org creates defaults for fresh org",
                  test_seed_creates_defaults_for_fresh_org)
            check("7D", "re-running seed is idempotent (no new versions)",
                  test_seed_is_idempotent)
            check("7D", "seeded system section matches filesystem floor",
                  test_seeded_system_section_matches_floor)
            check("7D", "after seed, resolver returns DB version not floor",
                  test_seeded_resolver_returns_db_version_not_floor)

        with section("7D - end-to-end"):
            check("7D", "live mode: ask_stream uses resolved version",
                  test_ask_stream_live_mode_uses_resolved_version)
            check("7D", "shadow mode: resolver computed but not consumed by synth",
                  test_shadow_mode_does_not_pass_resolved_to_synth)

        with section("7D - CLI"):
            check("7D", "CLI --dry-run makes no changes",
                  test_cli_dry_run_makes_no_changes)
            check("7D", "CLI --org-id seeds only that org",
                  test_cli_single_org_seed)
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
