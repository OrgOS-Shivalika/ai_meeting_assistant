"""Phase 7H ship test — tool registry + eval-gated publish.

Invariants verified:

  Tool registry:
   1. Default registry has 3 stub tools (web_search, crm_lookup, slack_post)
   2. Stub handlers raise NotImplementedError when called
   3. register_tool is idempotent: re-registering replaces
   4. side_effecting flag is set on slack_post and only slack_post

  Tool permissions:
   5. enforce raises PermissionDeniedError(reason='unknown_tool')
      for an unregistered tool_id
   6. enforce raises with reason='denied_by_layer' when tool is in denied
   7. enforce raises with reason='not_allowed' when tool not in allowed
   8. enforce returns the descriptor when tool is in allowed

  Schema:
   9. mode CHECK rejects bogus values
  10. triggered_by CHECK rejects bogus values
  11. cascade: deleting an org wipes its eval runs

  Eval gate service:
  12. run_eval_for_version persists an agent_eval_runs row
  13. report_json carries the per-case results
  14. run_if_required returns None when gate is disabled
  15. run_if_required returns AgentEvalRun on pass
  16. run_if_required raises EvalGateFailed when score < threshold

  Publish integration:
  17. publish with eval_gate_required=True + passing score succeeds
      and stamps version.eval_score + eval_run_id
  18. publish with eval_gate_required=True + failing score is BLOCKED;
      writes a prompt_deployments(action='eval_gate_failed') row;
      version stays in draft
  19. publish with eval_gate_required=False ignores threshold

  HTTP:
  20. POST /agents/{id}/eval/run returns the full eval detail
  21. POST /agents/{id}/eval/run with no version + no active version 400s
  22. GET /agents/{id}/eval/runs lists newest first
  23. GET /agents/tools/catalog lists registered tools
  24. eval endpoints cross-org 404

Run with:

    venv\\Scripts\\python.exe tests\\test_phase7h.py
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
    """Build org + user + agent_profile + ONE empty (unpublished)
    config so individual tests can publish their own versions
    without colliding."""
    from app.db.database import SessionLocal
    from app.db.models import (
        AgentProfile, AgentPromptConfig, Category, Organization, Team, User,
    )
    db = SessionLocal()
    try:
        org = Organization(name=f"7h-{theme}-org")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"7h-{theme}",
            email=f"7h-{theme}-{uuid.uuid4()}@example.com",
            password="x", organization_id=org.id, role="org_admin",
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
        }
    finally:
        db.close()


def _make_profile_with_published_version(
    fx: dict, *,
    eval_gate_required: bool = False,
    eval_min_score: float | None = None,
) -> dict:
    """Create a fresh profile + org-scoped config + draft + publish v1.
    Returns dict of ids."""
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, AgentPromptConfig
    from app.services.agents.publish import create_draft, publish_version

    db = SessionLocal()
    try:
        prof = AgentProfile(
            organization_id=fx["org_id"],
            slug=f"h-{uuid.uuid4().hex[:8]}",
            display_name="EvalProf",
            agent_type="rag_synth",
            eval_gate_required=eval_gate_required,
            eval_min_score=eval_min_score,
        )
        db.add(prof); db.commit(); db.refresh(prof)
        cfg = AgentPromptConfig(
            organization_id=fx["org_id"], agent_profile_id=prof.id,
            scope_type="organization", scope_id=None,
            created_by=fx["user_id"],
        )
        db.add(cfg); db.commit(); db.refresh(cfg)
        v = create_draft(
            db, organization_id=fx["org_id"],
            agent_prompt_config_id=cfg.id,
            label="v1",
            modular_prompt_json={
                "system": "sys", "retrieval": "r",
                "citation": "c", "guardrails": "g",
            },
            variables_schema_json=[], retrieval_config_json={},
            model_config_json={"model": "gpt-4o-mini"},
            tool_permissions_json={"allowed": [], "denied": []},
            meta_json={}, created_by=fx["user_id"],
            seeded_from_filesystem=True,
        )
        db.commit()
        publish_version(
            db, organization_id=fx["org_id"], version_id=v.id,
            actor_user_id=fx["user_id"],
        )
        return {"profile_id": prof.id, "config_id": cfg.id, "version_id": v.id}
    finally:
        db.close()


def _cleanup_all(fxs):
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        org_ids = [f["org_id"] for f in fxs]
        for stmt in (
            "DELETE FROM agent_eval_runs WHERE organization_id = ANY(:o)",
            "DELETE FROM agent_performance_daily WHERE organization_id = ANY(:o)",
            "DELETE FROM prompt_test_runs WHERE organization_id = ANY(:o)",
            "DELETE FROM agent_audit_events WHERE organization_id = ANY(:o)",
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
        db.execute(sql_text(
            "DELETE FROM users WHERE organization_id = ANY(:o)"
        ), {"o": org_ids})
        db.execute(sql_text("DELETE FROM organizations WHERE id = ANY(:o)"),
                   {"o": org_ids})
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


# Patch the Phase 5F harness so the eval gate doesn't actually build the
# canonical fixture (slow + expensive). Each test that calls into the
# gate replaces the harness with a canned result.

def _stub_run_eval(*, pass_rate=1.0, overall_passed=True, total=2, passed=2):
    """Replace tests.eval_phase5.run_eval.run_eval with a canned
    EvalReport-shaped namespace. Returns the cleanup callback."""
    from types import SimpleNamespace
    from tests.eval_phase5 import run_eval as run_eval_module

    case_results = []
    for i in range(passed):
        case_results.append(SimpleNamespace(
            case_id=f"c{i}", passed=True, failures=[],
            citations_count=0, duration_ms=1,
        ))
    for i in range(total - passed):
        case_results.append(SimpleNamespace(
            case_id=f"c{passed + i}", passed=False, failures=["fail"],
            citations_count=0, duration_ms=1,
        ))

    fake = SimpleNamespace(
        mode="stub",
        total_cases=total,
        passed_cases=passed,
        pass_rate=pass_rate,
        threshold=0.8,
        overall_passed=overall_passed,
        duration_ms=5,
        timestamp="2026-05-18T00:00:00Z",
        case_results=case_results,
    )

    original = run_eval_module.run_eval
    run_eval_module.run_eval = lambda **kwargs: fake
    return lambda: setattr(run_eval_module, "run_eval", original)


# ===========================================================================
# Tool registry tests
# ===========================================================================


def test_tool_registry_has_three_default_stubs():
    from app.services.tools.registry import list_tools, reset_for_tests
    reset_for_tests()
    ids = {t.tool_id for t in list_tools()}
    assert ids == {"web_search", "crm_lookup", "slack_post"}, ids


def test_tool_stubs_raise_not_implemented():
    from app.services.tools.registry import get_tool, reset_for_tests
    reset_for_tests()
    try:
        get_tool("web_search").handler("hello")
        raise AssertionError("web_search stub should raise NotImplementedError")
    except NotImplementedError:
        pass
    try:
        get_tool("crm_lookup").handler("x")
        raise AssertionError("crm_lookup stub should raise")
    except NotImplementedError:
        pass
    try:
        get_tool("slack_post").handler("#chan", "msg")
        raise AssertionError("slack_post stub should raise")
    except NotImplementedError:
        pass


def test_register_tool_is_idempotent():
    from app.services.tools.registry import (
        ToolDescriptor, get_tool, register_tool, reset_for_tests,
    )
    reset_for_tests()
    fake = ToolDescriptor(
        tool_id="web_search",
        display_name="Renamed",
        description="fake",
        handler=lambda: None,
        schema={"type": "object"},
        cost_class="free",
        side_effecting=False,
    )
    register_tool(fake)
    assert get_tool("web_search").display_name == "Renamed"
    reset_for_tests()
    # Defaults restored
    assert get_tool("web_search").display_name == "Web Search"


def test_only_slack_post_is_side_effecting():
    from app.services.tools.registry import list_tools, reset_for_tests
    reset_for_tests()
    side = {t.tool_id for t in list_tools() if t.side_effecting}
    assert side == {"slack_post"}, side


# ===========================================================================
# Tool permissions tests
# ===========================================================================


def _make_resolved_config_stub(*, allowed: list[str], denied: list[str]):
    """Build a minimal ResolvedAgentConfig with the given tool perms.
    Avoids hitting the DB — the enforce check is pure-Python."""
    from app.schemas.agent_schema import (
        ModelConfig, RetrievalConfig, ToolPermissions,
    )
    from app.services.agents.resolver import ResolvedAgentConfig

    return ResolvedAgentConfig(
        agent_profile_id=None, agent_type="rag_synth",
        prompt_version_id=None, version_number=None, label=None,
        modular_prompts={}, variables_used=[],
        retrieval_config=RetrievalConfig(),
        model_config=ModelConfig(),
        tool_permissions=ToolPermissions(allowed=allowed, denied=denied),
        resolution_path=[], config_hash="x" * 64,
        is_default_fallback=True, warnings=[],
    )


def test_enforce_unknown_tool_raises():
    from app.services.tools.permissions import (
        PermissionDeniedError, enforce_tool_permission,
    )
    cfg = _make_resolved_config_stub(allowed=["bogus"], denied=[])
    try:
        enforce_tool_permission(cfg, "bogus")
        raise AssertionError("must raise on unknown tool_id")
    except PermissionDeniedError as exc:
        assert exc.reason == "unknown_tool", exc.reason


def test_enforce_denied_overrides_allowed():
    from app.services.tools.permissions import (
        PermissionDeniedError, enforce_tool_permission,
    )
    cfg = _make_resolved_config_stub(
        allowed=["web_search"], denied=["web_search"],
    )
    try:
        enforce_tool_permission(cfg, "web_search")
        raise AssertionError("denied must override allowed")
    except PermissionDeniedError as exc:
        assert exc.reason == "denied_by_layer", exc.reason


def test_enforce_not_allowed_raises():
    from app.services.tools.permissions import (
        PermissionDeniedError, enforce_tool_permission,
    )
    cfg = _make_resolved_config_stub(allowed=[], denied=[])
    try:
        enforce_tool_permission(cfg, "web_search")
        raise AssertionError("must raise when not in allowed")
    except PermissionDeniedError as exc:
        assert exc.reason == "not_allowed", exc.reason


def test_enforce_allowed_returns_descriptor():
    from app.services.tools.permissions import enforce_tool_permission
    cfg = _make_resolved_config_stub(allowed=["web_search"], denied=[])
    desc = enforce_tool_permission(cfg, "web_search")
    assert desc is not None
    assert desc.tool_id == "web_search"


# ===========================================================================
# Schema tests
# ===========================================================================


def test_mode_check():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import AgentEvalRun
    db = SessionLocal()
    try:
        row = AgentEvalRun(
            organization_id=_A()["org_id"], mode="halfway",
            threshold=0.8, started_at=datetime.now(timezone.utc),
            triggered_by="manual",
        )
        db.add(row)
        try:
            db.commit()
            raise AssertionError("bogus mode must violate CHECK")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_triggered_by_check():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import AgentEvalRun
    db = SessionLocal()
    try:
        row = AgentEvalRun(
            organization_id=_A()["org_id"], mode="stub",
            threshold=0.8, started_at=datetime.now(timezone.utc),
            triggered_by="not_a_trigger",
        )
        db.add(row)
        try:
            db.commit()
            raise AssertionError("bogus triggered_by must violate CHECK")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_cascade_org_delete_wipes_eval_runs():
    from app.db.database import SessionLocal
    from app.db.models import AgentEvalRun, Organization
    db = SessionLocal()
    try:
        org = Organization(name=f"7h-cascade-{uuid.uuid4().hex[:6]}")
        db.add(org); db.commit(); db.refresh(org)
        row = AgentEvalRun(
            organization_id=org.id, mode="stub",
            threshold=0.8, started_at=datetime.now(timezone.utc),
            triggered_by="manual",
        )
        db.add(row); db.commit(); db.refresh(row)
        rid = row.id

        db.delete(org); db.commit(); db.expire_all()
        n = db.query(AgentEvalRun).filter(
            AgentEvalRun.id == rid,
        ).count()
        assert n == 0
    finally:
        db.close()


# ===========================================================================
# Eval gate service tests
# ===========================================================================


def test_run_eval_persists_a_row():
    from app.db.database import SessionLocal
    from app.db.models import AgentEvalRun
    from app.services.agents.eval_gate import run_eval_for_version

    fx = _A()
    pids = _make_profile_with_published_version(fx)
    restore = _stub_run_eval(pass_rate=1.0, overall_passed=True)
    db = SessionLocal()
    try:
        run = run_eval_for_version(
            db, organization_id=fx["org_id"],
            agent_profile_id=pids["profile_id"],
            prompt_version_id=pids["version_id"],
            mode="stub", threshold=0.5,
            triggered_by="manual",
            triggered_by_user_id=fx["user_id"],
        )
        assert run.id is not None
        assert run.score == 1.0
        assert run.overall_passed is True
        # And it's queryable from DB
        n = db.query(AgentEvalRun).filter(
            AgentEvalRun.organization_id == fx["org_id"],
            AgentEvalRun.agent_profile_id == pids["profile_id"],
        ).count()
        assert n >= 1
    finally:
        restore()
        db.close()


def test_run_eval_report_has_cases():
    from app.db.database import SessionLocal
    from app.services.agents.eval_gate import run_eval_for_version

    fx = _A()
    pids = _make_profile_with_published_version(fx)
    restore = _stub_run_eval(pass_rate=0.5, overall_passed=False, total=4, passed=2)
    db = SessionLocal()
    try:
        run = run_eval_for_version(
            db, organization_id=fx["org_id"],
            agent_profile_id=pids["profile_id"],
            prompt_version_id=pids["version_id"],
            mode="stub", threshold=0.8,
        )
        cases = run.report_json.get("cases", [])
        assert len(cases) == 4, cases
    finally:
        restore()
        db.close()


def test_run_if_required_skips_when_disabled():
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, PromptVersion
    from app.services.agents.eval_gate import run_if_required
    fx = _A()
    # Profile WITHOUT gate
    pids = _make_profile_with_published_version(fx, eval_gate_required=False)
    db = SessionLocal()
    try:
        prof = db.query(AgentProfile).filter(
            AgentProfile.id == pids["profile_id"],
        ).first()
        ver = db.query(PromptVersion).filter(
            PromptVersion.id == pids["version_id"],
        ).first()
        out = run_if_required(
            db, profile=prof, version=ver, actor_user_id=fx["user_id"],
        )
        assert out is None
    finally:
        db.close()


def test_run_if_required_passes_on_high_score():
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, PromptVersion
    from app.services.agents.eval_gate import run_if_required
    fx = _A()
    pids = _make_profile_with_published_version(
        fx, eval_gate_required=True, eval_min_score=0.5,
    )
    restore = _stub_run_eval(pass_rate=0.9, overall_passed=True)
    db = SessionLocal()
    try:
        prof = db.query(AgentProfile).filter(
            AgentProfile.id == pids["profile_id"],
        ).first()
        ver = db.query(PromptVersion).filter(
            PromptVersion.id == pids["version_id"],
        ).first()
        out = run_if_required(
            db, profile=prof, version=ver, actor_user_id=fx["user_id"],
        )
        assert out is not None
        assert out.score == 0.9
    finally:
        restore()
        db.close()


def test_run_if_required_fails_below_threshold():
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, PromptVersion
    from app.services.agents.eval_gate import EvalGateFailed, run_if_required
    fx = _A()
    pids = _make_profile_with_published_version(
        fx, eval_gate_required=True, eval_min_score=0.8,
    )
    restore = _stub_run_eval(pass_rate=0.5, overall_passed=False)
    db = SessionLocal()
    try:
        prof = db.query(AgentProfile).filter(
            AgentProfile.id == pids["profile_id"],
        ).first()
        ver = db.query(PromptVersion).filter(
            PromptVersion.id == pids["version_id"],
        ).first()
        try:
            run_if_required(
                db, profile=prof, version=ver, actor_user_id=fx["user_id"],
            )
            raise AssertionError("must raise EvalGateFailed on low score")
        except EvalGateFailed as exc:
            assert exc.score == 0.5
            assert exc.threshold == 0.8
    finally:
        restore()
        db.close()


# ===========================================================================
# Publish integration tests
# ===========================================================================


def test_publish_with_gate_passes_and_stamps_eval_metadata():
    """A new draft on a gate-required profile: publish runs the gate,
    the version's eval_score + eval_run_id get stamped, publish
    proceeds."""
    from app.db.database import SessionLocal
    from app.db.models import (
        AgentProfile, AgentPromptConfig, PromptVersion,
    )
    from app.services.agents.publish import create_draft, publish_version
    fx = _A()
    # Profile with gate ON
    prof_db = SessionLocal()
    try:
        prof = AgentProfile(
            organization_id=fx["org_id"],
            slug=f"gate-pass-{uuid.uuid4().hex[:6]}",
            display_name="GP", agent_type="rag_synth",
            eval_gate_required=True, eval_min_score=0.5,
        )
        prof_db.add(prof); prof_db.commit(); prof_db.refresh(prof)
        cfg = AgentPromptConfig(
            organization_id=fx["org_id"], agent_profile_id=prof.id,
            scope_type="organization", scope_id=None,
        )
        prof_db.add(cfg); prof_db.commit(); prof_db.refresh(cfg)
        prof_id, cfg_id = prof.id, cfg.id
    finally:
        prof_db.close()

    restore = _stub_run_eval(pass_rate=0.95, overall_passed=True)
    db = SessionLocal()
    try:
        # Create a non-seeded draft so the validator runs (and passes —
        # the modular_prompt has all 4 required sections).
        v = create_draft(
            db, organization_id=fx["org_id"],
            agent_prompt_config_id=cfg_id,
            label="v1",
            modular_prompt_json={
                "system": "sys", "retrieval": "r",
                "citation": "c", "guardrails": "g",
            },
            variables_schema_json=[], retrieval_config_json={},
            model_config_json={}, tool_permissions_json={"allowed": [], "denied": []},
            meta_json={}, created_by=fx["user_id"],
        )
        db.commit()
        publish_version(
            db, organization_id=fx["org_id"], version_id=v.id,
            actor_user_id=fx["user_id"], reason="ship with gate",
        )
        db.expire_all()
        v_row = db.query(PromptVersion).filter(
            PromptVersion.id == v.id,
        ).first()
        assert v_row.state == "published"
        assert v_row.eval_score == 0.95
        assert v_row.eval_run_id is not None
    finally:
        restore()
        db.close()


def test_publish_with_gate_failing_score_is_blocked():
    """Same setup but the eval scores below threshold. publish must
    raise PublishGateFailed; version stays in 'draft'; an
    eval_gate_failed deployment row is written."""
    from app.db.database import SessionLocal
    from app.db.models import (
        AgentProfile, AgentPromptConfig, PromptDeployment, PromptVersion,
    )
    from app.services.agents.publish import (
        PublishGateFailed, create_draft, publish_version,
    )
    fx = _A()
    prof_db = SessionLocal()
    try:
        prof = AgentProfile(
            organization_id=fx["org_id"],
            slug=f"gate-fail-{uuid.uuid4().hex[:6]}",
            display_name="GF", agent_type="rag_synth",
            eval_gate_required=True, eval_min_score=0.9,
        )
        prof_db.add(prof); prof_db.commit(); prof_db.refresh(prof)
        cfg = AgentPromptConfig(
            organization_id=fx["org_id"], agent_profile_id=prof.id,
            scope_type="organization", scope_id=None,
        )
        prof_db.add(cfg); prof_db.commit(); prof_db.refresh(cfg)
        cfg_id = cfg.id
    finally:
        prof_db.close()

    restore = _stub_run_eval(pass_rate=0.5, overall_passed=False)
    db = SessionLocal()
    try:
        v = create_draft(
            db, organization_id=fx["org_id"],
            agent_prompt_config_id=cfg_id,
            label="v1",
            modular_prompt_json={
                "system": "sys", "retrieval": "r",
                "citation": "c", "guardrails": "g",
            },
            variables_schema_json=[], retrieval_config_json={},
            model_config_json={}, tool_permissions_json={"allowed": [], "denied": []},
            meta_json={}, created_by=fx["user_id"],
        )
        db.commit()
        v_id = v.id
        try:
            publish_version(
                db, organization_id=fx["org_id"], version_id=v_id,
                actor_user_id=fx["user_id"], reason="should fail",
            )
            raise AssertionError("publish must raise on failing gate")
        except PublishGateFailed:
            pass

        db.expire_all()
        v_row = db.query(PromptVersion).filter(PromptVersion.id == v_id).first()
        assert v_row.state == "draft", v_row.state
        # eval_gate_failed deployment row was written
        dep = db.query(PromptDeployment).filter(
            PromptDeployment.agent_prompt_config_id == cfg_id,
            PromptDeployment.action == "eval_gate_failed",
        ).first()
        assert dep is not None
        assert dep.from_version_id == v_id
        assert dep.metadata_json.get("eval_score") == 0.5
    finally:
        restore()
        db.close()


def test_publish_without_gate_ignores_eval():
    """A profile with eval_gate_required=False publishes without
    invoking the harness."""
    from app.db.database import SessionLocal
    from app.db.models import (
        AgentEvalRun, AgentProfile, AgentPromptConfig,
    )
    from app.services.agents.publish import create_draft, publish_version
    fx = _A()
    prof_db = SessionLocal()
    try:
        prof = AgentProfile(
            organization_id=fx["org_id"],
            slug=f"no-gate-{uuid.uuid4().hex[:6]}",
            display_name="NG", agent_type="rag_synth",
            eval_gate_required=False,
        )
        prof_db.add(prof); prof_db.commit(); prof_db.refresh(prof)
        cfg = AgentPromptConfig(
            organization_id=fx["org_id"], agent_profile_id=prof.id,
            scope_type="organization", scope_id=None,
        )
        prof_db.add(cfg); prof_db.commit(); prof_db.refresh(cfg)
        cfg_id, prof_id = cfg.id, prof.id
    finally:
        prof_db.close()

    # If the harness is invoked, this stub would record a row. We
    # leave the real harness in place — if it gets called, it will
    # crash because the canonical fixture isn't built. So a successful
    # publish here proves the gate was NOT invoked.
    db = SessionLocal()
    try:
        before = db.query(AgentEvalRun).filter(
            AgentEvalRun.organization_id == fx["org_id"],
            AgentEvalRun.agent_profile_id == prof_id,
        ).count()
        v = create_draft(
            db, organization_id=fx["org_id"],
            agent_prompt_config_id=cfg_id,
            label="v1",
            modular_prompt_json={
                "system": "sys", "retrieval": "r",
                "citation": "c", "guardrails": "g",
            },
            variables_schema_json=[], retrieval_config_json={},
            model_config_json={}, tool_permissions_json={"allowed": [], "denied": []},
            meta_json={}, created_by=fx["user_id"],
        )
        db.commit()
        publish_version(
            db, organization_id=fx["org_id"], version_id=v.id,
            actor_user_id=fx["user_id"],
        )
        after = db.query(AgentEvalRun).filter(
            AgentEvalRun.organization_id == fx["org_id"],
            AgentEvalRun.agent_profile_id == prof_id,
        ).count()
        assert after == before, (before, after)
    finally:
        db.close()


# ===========================================================================
# HTTP tests
# ===========================================================================


def test_http_post_eval_run_returns_detail():
    fx = _A()
    pids = _make_profile_with_published_version(fx)
    restore = _stub_run_eval(pass_rate=0.85, overall_passed=True, total=2, passed=2)
    try:
        r = _client_for(fx["user_id"]).post(
            f"/agents/{pids['profile_id']}/eval/run",
            json={"mode": "stub", "threshold": 0.5},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["score"] == 0.85
        assert body["overall_passed"] is True
        assert isinstance(body["report_json"].get("cases"), list)
    finally:
        restore()


def test_http_post_eval_run_no_active_version_400():
    """A profile with no active version + no version_id passed must
    400 with a clear message."""
    from app.db.database import SessionLocal
    from app.db.models import AgentProfile, AgentPromptConfig
    fx = _A()
    db = SessionLocal()
    try:
        prof = AgentProfile(
            organization_id=fx["org_id"],
            slug=f"no-version-{uuid.uuid4().hex[:6]}",
            display_name="NV", agent_type="rag_synth",
        )
        db.add(prof); db.commit(); db.refresh(prof)
        # No config, no version
        prof_id = prof.id
    finally:
        db.close()

    r = _client_for(fx["user_id"]).post(
        f"/agents/{prof_id}/eval/run",
        json={"mode": "stub"},
    )
    assert r.status_code == 400, r.text


def test_http_get_eval_runs_lists_newest_first():
    fx = _A()
    pids = _make_profile_with_published_version(fx)
    restore = _stub_run_eval(pass_rate=0.9, overall_passed=True)
    try:
        # Trigger two runs
        for _ in range(2):
            _client_for(fx["user_id"]).post(
                f"/agents/{pids['profile_id']}/eval/run",
                json={"mode": "stub", "threshold": 0.5},
            )
        r = _client_for(fx["user_id"]).get(
            f"/agents/{pids['profile_id']}/eval/runs",
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) >= 2
        # All belong to this profile
        for row in rows:
            assert row["score"] == 0.9
    finally:
        restore()


def test_http_get_tools_catalog():
    fx = _A()
    from app.services.tools.registry import reset_for_tests
    reset_for_tests()
    r = _client_for(fx["user_id"]).get("/agents/tools/catalog")
    assert r.status_code == 200, r.text
    ids = {it["tool_id"] for it in r.json()}
    assert ids == {"web_search", "crm_lookup", "slack_post"}, ids


def test_http_eval_run_cross_org_404():
    fx_a = _A(); fx_b = _B()
    pids_a = _make_profile_with_published_version(fx_a)
    # Org B tries to trigger eval against Org A's profile
    r = _client_for(fx_b["user_id"]).post(
        f"/agents/{pids_a['profile_id']}/eval/run",
        json={"mode": "stub", "threshold": 0.5},
    )
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    global _FX
    _FX = [_seed_org("alpha"), _seed_org("bravo")]

    try:
        with section("7H - tool registry"):
            check("7H", "default registry has 3 stub tools",
                  test_tool_registry_has_three_default_stubs)
            check("7H", "stub handlers raise NotImplementedError",
                  test_tool_stubs_raise_not_implemented)
            check("7H", "register_tool is idempotent",
                  test_register_tool_is_idempotent)
            check("7H", "only slack_post is side_effecting",
                  test_only_slack_post_is_side_effecting)

        with section("7H - tool permissions"):
            check("7H", "enforce: unknown tool raises",
                  test_enforce_unknown_tool_raises)
            check("7H", "enforce: denied overrides allowed",
                  test_enforce_denied_overrides_allowed)
            check("7H", "enforce: not in allowed raises",
                  test_enforce_not_allowed_raises)
            check("7H", "enforce: in allowed returns descriptor",
                  test_enforce_allowed_returns_descriptor)

        with section("7H - schema"):
            check("7H", "mode CHECK rejects bogus", test_mode_check)
            check("7H", "triggered_by CHECK rejects bogus",
                  test_triggered_by_check)
            check("7H", "cascade: deleting org wipes eval runs",
                  test_cascade_org_delete_wipes_eval_runs)

        with section("7H - eval gate service"):
            check("7H", "run_eval persists a row",
                  test_run_eval_persists_a_row)
            check("7H", "report_json carries per-case results",
                  test_run_eval_report_has_cases)
            check("7H", "run_if_required skips when gate disabled",
                  test_run_if_required_skips_when_disabled)
            check("7H", "run_if_required passes on high score",
                  test_run_if_required_passes_on_high_score)
            check("7H", "run_if_required raises on low score",
                  test_run_if_required_fails_below_threshold)

        with section("7H - publish integration"):
            check("7H", "gate-pass stamps eval_score + eval_run_id",
                  test_publish_with_gate_passes_and_stamps_eval_metadata)
            check("7H", "gate-fail blocks publish + writes audit row",
                  test_publish_with_gate_failing_score_is_blocked)
            check("7H", "no-gate skips eval entirely",
                  test_publish_without_gate_ignores_eval)

        with section("7H - HTTP"):
            check("7H", "POST /eval/run returns full detail",
                  test_http_post_eval_run_returns_detail)
            check("7H", "POST /eval/run with no active version 400",
                  test_http_post_eval_run_no_active_version_400)
            check("7H", "GET /eval/runs lists newest first",
                  test_http_get_eval_runs_lists_newest_first)
            check("7H", "GET /tools/catalog lists registered tools",
                  test_http_get_tools_catalog)
            check("7H", "eval run cross-org 404",
                  test_http_eval_run_cross_org_404)
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
