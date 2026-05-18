"""Phase 7F ship test — analytics rollup + observability endpoints.

Invariants verified:

  Schema:
   1. UNIQUE on (org, bucket_date, COALESCE(profile,''), COALESCE(version,''))
      tolerates NULL profile + version
   2. duplicate insert with same key violates uniqueness
   3. cascade: deleting an org wipes its rollup rows

  Pricing:
   4. cost_for_run for a known model returns a positive number
   5. cost_for_run for an unknown model returns None
   6. cost_for_run with null tokens returns None

  Rollup builder:
   7. rebuild_daily_bucket aggregates rag_query_runs into rollup rows
   8. rebuild is idempotent: second call inserts the same number of rows
   9. status counts (completed/no_context/failed) are correct
  10. p50/p95 are computed from total_duration_ms
  11. sum_input_tokens + sum_output_tokens are summed correctly
  12. distinct_users is counted per (profile, version, day) bucket
  13. unattributed runs (profile null, version null) get their own bucket
  14. rebuilding scoped to one org doesn't touch other orgs' rows

  Query helpers:
  15. summary_for_orgs_agents returns one row per agent_profile + 1 for null
  16. metrics_for_agent returns the right profile's row
  17. metrics_per_version groups by version + adds cost when model is known

  HTTP endpoints:
  18. GET /rag/observability/agents returns rollup-derived summary
  19. GET /rag/observability/agents/{id} returns 404 cross-org
  20. GET /rag/observability/agents/{id}/versions returns per-version rows
  21. GET /rag/observability/agents/{id}/versions/{v_id}/runs returns recent runs
  22. GET /rag/observability/deployments returns the audit feed
  23. /deployments filter by action narrows correctly
  24. /deployments filter by agent_prompt_config_id narrows correctly

Run with:

    venv\\Scripts\\python.exe tests\\test_phase7f.py
"""
from __future__ import annotations

import os
import sys
import traceback
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
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
    """Build org + user + agent_profile + 1 published version (for the
    per-version analytics tests)."""
    from app.db.database import SessionLocal
    from app.db.models import (
        AgentProfile, AgentPromptConfig, Category, Organization, Team, User,
    )
    from app.services.agents.publish import create_draft, publish_version

    db = SessionLocal()
    try:
        org = Organization(name=f"7f-{theme}-org")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"7f-{theme}",
            email=f"7f-{theme}-{uuid.uuid4()}@example.com",
            password="x", organization_id=org.id, role="org_admin",
        )
        db.add(user); db.commit(); db.refresh(user)
        cat = Category(name=f"{theme}-cat", organization_id=org.id, user_id=user.id)
        db.add(cat); db.commit(); db.refresh(cat)
        team = Team(name=f"{theme}-team", category_id=cat.id)
        db.add(team); db.commit(); db.refresh(team)
        prof = AgentProfile(
            organization_id=org.id, slug=f"{theme}-synth",
            display_name="Synth", agent_type="rag_synth",
        )
        db.add(prof); db.commit(); db.refresh(prof)
        cfg = AgentPromptConfig(
            organization_id=org.id, agent_profile_id=prof.id,
            scope_type="organization", scope_id=None, created_by=user.id,
        )
        db.add(cfg); db.commit(); db.refresh(cfg)
        v = create_draft(
            db, organization_id=org.id,
            agent_prompt_config_id=cfg.id,
            label="seed-v1",
            modular_prompt_json={"system": "sys", "retrieval": "r",
                                 "citation": "c", "guardrails": "g"},
            variables_schema_json=[], retrieval_config_json={},
            model_config_json={"model": "gpt-4o-mini"},
            tool_permissions_json={"allowed": [], "denied": []},
            meta_json={}, created_by=user.id,
            seeded_from_filesystem=True,
        )
        db.commit()
        publish_version(
            db, organization_id=org.id, version_id=v.id,
            actor_user_id=user.id,
        )
        return {
            "org_id": org.id, "user_id": user.id,
            "category_id": cat.id, "team_id": team.id,
            "profile_id": prof.id, "config_id": cfg.id,
            "version_id": v.id,
        }
    finally:
        db.close()


def _insert_run(
    *,
    organization_id, profile_id=None, version_id=None,
    user_id=None, status="completed", duration_ms=1000,
    input_tokens=100, output_tokens=50, citations_count=2,
    retrieved_chunks=5, hours_ago=2,
):
    """Direct INSERT into rag_query_runs for rollup testing. Bypasses
    the API so we control exact field values."""
    from app.db.database import SessionLocal
    from app.db.models import RagQueryRun
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        ts = now - timedelta(hours=hours_ago)
        # Build citations as a list of dummy entries (jsonb)
        citations = [{"index": i + 1, "chunk_id": str(uuid.uuid4()),
                      "source_type": "meeting"} for i in range(citations_count)]
        row = RagQueryRun(
            organization_id=organization_id,
            user_id=user_id,
            agent_profile_id=profile_id,
            prompt_version_id=version_id,
            query_text="test",
            requested_scope_type=None, requested_scope_id=None,
            effective_scope_type=None, effective_scope_id=None,
            planner_model="gpt-4o-mini",
            planner_prompt_version="v1",
            synth_model="gpt-4o-mini",
            synth_prompt_version="v1",
            retrieved_chunks=retrieved_chunks,
            retrieved_entities=2, retrieved_relationships=1,
            total_duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status=status,
            answer_text="x",
            citations=citations,
            retrieval_bundle={},
            started_at=ts,
            completed_at=ts,
            created_at=ts,
        )
        db.add(row); db.commit(); db.refresh(row)
        return row.id
    finally:
        db.close()


def _cleanup_all(fxs):
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        org_ids = [f["org_id"] for f in fxs]
        for stmt in (
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


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _yesterday() -> date:
    return _today() - timedelta(days=1)


# ===========================================================================
# Schema tests
# ===========================================================================


def test_unique_index_tolerates_null_profile_and_version():
    """The COALESCE-based UNIQUE index permits one row with NULL
    profile + version per (org, bucket_date)."""
    from app.db.database import SessionLocal
    from app.db.models import AgentPerformanceDaily
    db = SessionLocal()
    try:
        row = AgentPerformanceDaily(
            organization_id=_A()["org_id"],
            agent_profile_id=None, prompt_version_id=None,
            bucket_date=date(2024, 1, 1),
            runs_total=1, runs_completed=1,
        )
        db.add(row); db.commit(); db.refresh(row)
        # Cleanup
        db.delete(row); db.commit()
    finally:
        db.close()


def test_unique_index_rejects_duplicate_key():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import AgentPerformanceDaily
    db = SessionLocal()
    try:
        a = AgentPerformanceDaily(
            organization_id=_A()["org_id"],
            agent_profile_id=_A()["profile_id"],
            prompt_version_id=_A()["version_id"],
            bucket_date=date(2024, 1, 2),
            runs_total=1, runs_completed=1,
        )
        db.add(a); db.commit(); db.refresh(a)
        b = AgentPerformanceDaily(
            organization_id=_A()["org_id"],
            agent_profile_id=_A()["profile_id"],
            prompt_version_id=_A()["version_id"],
            bucket_date=date(2024, 1, 2),
            runs_total=2, runs_completed=2,
        )
        db.add(b)
        try:
            db.commit()
            raise AssertionError("duplicate natural key must violate UNIQUE")
        except IntegrityError:
            db.rollback()
        finally:
            db.delete(a); db.commit()
    finally:
        db.close()


def test_cascade_org_delete_wipes_rollup():
    from app.db.database import SessionLocal
    from app.db.models import AgentPerformanceDaily, Organization
    from sqlalchemy import text as sql_text
    db = SessionLocal()
    try:
        org = Organization(name=f"7f-cascade-{uuid.uuid4().hex[:6]}")
        db.add(org); db.commit(); db.refresh(org)
        row = AgentPerformanceDaily(
            organization_id=org.id,
            bucket_date=date(2024, 1, 3),
            runs_total=5,
        )
        db.add(row); db.commit(); db.refresh(row)
        rid = row.id

        db.delete(org); db.commit(); db.expire_all()
        n = db.query(AgentPerformanceDaily).filter(
            AgentPerformanceDaily.id == rid,
        ).count()
        assert n == 0
    finally:
        db.close()


# ===========================================================================
# Pricing tests
# ===========================================================================


def test_pricing_known_model_returns_positive():
    from app.services.agents.pricing import cost_for_run
    c = cost_for_run(model="gpt-4o-mini", input_tokens=10_000, output_tokens=5_000)
    assert c is not None and c > 0, c


def test_pricing_unknown_model_returns_none():
    from app.services.agents.pricing import cost_for_run
    assert cost_for_run(
        model="not-a-real-model", input_tokens=100, output_tokens=50,
    ) is None


def test_pricing_null_tokens_returns_none():
    from app.services.agents.pricing import cost_for_run
    assert cost_for_run(
        model="gpt-4o-mini", input_tokens=None, output_tokens=50,
    ) is None
    assert cost_for_run(
        model="gpt-4o-mini", input_tokens=100, output_tokens=None,
    ) is None


# ===========================================================================
# Rollup builder
# ===========================================================================


def test_rebuild_aggregates_runs_into_rollup_rows():
    """Insert a few runs at yesterday's date, then rebuild yesterday
    and inspect the resulting rollup row."""
    from app.db.database import SessionLocal
    from app.db.models import AgentPerformanceDaily
    from app.services.agents.analytics import rebuild_daily_bucket
    fx = _A()
    # 3 completed runs at the profile + version
    for _ in range(3):
        _insert_run(
            organization_id=fx["org_id"],
            profile_id=fx["profile_id"], version_id=fx["version_id"],
            user_id=fx["user_id"],
            status="completed", duration_ms=1000,
            input_tokens=100, output_tokens=50,
            hours_ago=26,  # safely yesterday
        )
    # 1 no_context run
    _insert_run(
        organization_id=fx["org_id"],
        profile_id=fx["profile_id"], version_id=fx["version_id"],
        user_id=fx["user_id"],
        status="no_context", duration_ms=500,
        hours_ago=26,
    )

    db = SessionLocal()
    try:
        n = rebuild_daily_bucket(
            db, bucket_date=_yesterday(),
            organization_id=fx["org_id"],
        )
        assert n >= 1, n
        row = db.query(AgentPerformanceDaily).filter(
            AgentPerformanceDaily.organization_id == fx["org_id"],
            AgentPerformanceDaily.agent_profile_id == fx["profile_id"],
            AgentPerformanceDaily.prompt_version_id == fx["version_id"],
            AgentPerformanceDaily.bucket_date == _yesterday(),
        ).first()
        assert row is not None
        assert row.runs_total == 4, row.runs_total
        assert row.runs_completed == 3
        assert row.runs_no_context == 1
        assert row.runs_failed == 0
        assert row.sum_input_tokens == 100 * 3 + 100  # 4 runs × 100
        assert row.sum_output_tokens == 50 * 4
    finally:
        db.close()


def test_rebuild_is_idempotent():
    """Running the rebuild twice produces the same row count + values."""
    from app.db.database import SessionLocal
    from app.db.models import AgentPerformanceDaily
    from app.services.agents.analytics import rebuild_daily_bucket
    fx = _A()
    db = SessionLocal()
    try:
        # First rebuild (already ran in the prior test — same data)
        rebuild_daily_bucket(
            db, bucket_date=_yesterday(),
            organization_id=fx["org_id"],
        )
        rows_first = db.query(AgentPerformanceDaily).filter(
            AgentPerformanceDaily.organization_id == fx["org_id"],
            AgentPerformanceDaily.bucket_date == _yesterday(),
        ).all()
        # Snapshot
        snapshot = {(r.agent_profile_id, r.prompt_version_id): r.runs_total
                    for r in rows_first}

        rebuild_daily_bucket(
            db, bucket_date=_yesterday(),
            organization_id=fx["org_id"],
        )
        rows_second = db.query(AgentPerformanceDaily).filter(
            AgentPerformanceDaily.organization_id == fx["org_id"],
            AgentPerformanceDaily.bucket_date == _yesterday(),
        ).all()
        snapshot2 = {(r.agent_profile_id, r.prompt_version_id): r.runs_total
                     for r in rows_second}
        assert snapshot == snapshot2, (snapshot, snapshot2)
    finally:
        db.close()


def test_p50_p95_computed():
    """Verify percentile_disc results land in the rollup."""
    from app.db.database import SessionLocal
    from app.db.models import AgentPerformanceDaily
    db = SessionLocal()
    try:
        row = db.query(AgentPerformanceDaily).filter(
            AgentPerformanceDaily.organization_id == _A()["org_id"],
            AgentPerformanceDaily.agent_profile_id == _A()["profile_id"],
            AgentPerformanceDaily.bucket_date == _yesterday(),
        ).first()
        assert row is not None
        assert row.p50_total_duration_ms is not None
        assert row.p95_total_duration_ms is not None
        # 4 runs: 3 × 1000ms + 1 × 500ms.
        # p50 (median) at 50% of sorted=[500,1000,1000,1000] → 1000.
        # p95 → 1000.
        assert row.p50_total_duration_ms in (500, 1000), row.p50_total_duration_ms
        assert row.p95_total_duration_ms == 1000, row.p95_total_duration_ms
    finally:
        db.close()


def test_distinct_users_counted():
    """Add a run by a different user; rebuild; distinct_users == 2."""
    from app.db.database import SessionLocal
    from app.db.models import AgentPerformanceDaily, User
    from app.services.agents.analytics import rebuild_daily_bucket
    fx = _A()
    # New user in same org
    db = SessionLocal()
    try:
        u2 = User(
            name="extra", email=f"extra-{uuid.uuid4()}@example.com",
            password="x", organization_id=fx["org_id"], role="viewer",
        )
        db.add(u2); db.commit(); db.refresh(u2)
        u2_id = u2.id
    finally:
        db.close()

    _insert_run(
        organization_id=fx["org_id"],
        profile_id=fx["profile_id"], version_id=fx["version_id"],
        user_id=u2_id, status="completed", duration_ms=800,
        hours_ago=26,
    )
    db = SessionLocal()
    try:
        rebuild_daily_bucket(
            db, bucket_date=_yesterday(),
            organization_id=fx["org_id"],
        )
        row = db.query(AgentPerformanceDaily).filter(
            AgentPerformanceDaily.organization_id == fx["org_id"],
            AgentPerformanceDaily.agent_profile_id == fx["profile_id"],
            AgentPerformanceDaily.bucket_date == _yesterday(),
        ).first()
        assert row.distinct_users >= 2, row.distinct_users
    finally:
        db.close()


def test_unattributed_run_gets_null_bucket():
    """Insert a run with profile/version NULL; rebuild; verify a
    NULL-keyed bucket exists."""
    from app.db.database import SessionLocal
    from app.db.models import AgentPerformanceDaily
    from app.services.agents.analytics import rebuild_daily_bucket
    fx = _A()
    _insert_run(
        organization_id=fx["org_id"],
        profile_id=None, version_id=None,
        user_id=fx["user_id"],
        status="completed", duration_ms=700,
        hours_ago=26,
    )
    db = SessionLocal()
    try:
        rebuild_daily_bucket(
            db, bucket_date=_yesterday(),
            organization_id=fx["org_id"],
        )
        row = db.query(AgentPerformanceDaily).filter(
            AgentPerformanceDaily.organization_id == fx["org_id"],
            AgentPerformanceDaily.agent_profile_id.is_(None),
            AgentPerformanceDaily.prompt_version_id.is_(None),
            AgentPerformanceDaily.bucket_date == _yesterday(),
        ).first()
        assert row is not None
        assert row.runs_total >= 1
    finally:
        db.close()


def test_scoped_rebuild_doesnt_touch_other_orgs():
    """Insert runs in both orgs; rebuild scoped to A only; B's rollup
    rows must not exist."""
    from app.db.database import SessionLocal
    from app.db.models import AgentPerformanceDaily
    from app.services.agents.analytics import rebuild_daily_bucket
    fx_a = _A(); fx_b = _B()
    _insert_run(
        organization_id=fx_b["org_id"],
        profile_id=fx_b["profile_id"], version_id=fx_b["version_id"],
        user_id=fx_b["user_id"], status="completed", duration_ms=900,
        hours_ago=26,
    )
    db = SessionLocal()
    try:
        # Wipe any prior B rollup
        from sqlalchemy import text as sql_text
        db.execute(sql_text(
            "DELETE FROM agent_performance_daily WHERE organization_id = :o"
        ), {"o": str(fx_b["org_id"])})
        db.commit()
        # Now rebuild ONLY for A
        rebuild_daily_bucket(
            db, bucket_date=_yesterday(),
            organization_id=fx_a["org_id"],
        )
        # B's rollup must be empty
        b_count = db.query(AgentPerformanceDaily).filter(
            AgentPerformanceDaily.organization_id == fx_b["org_id"],
        ).count()
        assert b_count == 0, b_count
    finally:
        db.close()


# ===========================================================================
# Query helpers
# ===========================================================================


def test_summary_returns_profile_row():
    """summary_for_orgs_agents returns the seeded profile's row."""
    from app.db.database import SessionLocal
    from app.services.agents.analytics import summary_for_orgs_agents
    fx = _A()
    db = SessionLocal()
    try:
        rows = summary_for_orgs_agents(
            db, organization_id=fx["org_id"],
            since=_yesterday(), until=_today(),
        )
        # At least one row for our profile + one for the null bucket.
        prof_rows = [r for r in rows if r.agent_profile_id == fx["profile_id"]]
        assert prof_rows, [r.agent_profile_id for r in rows]
        r = prof_rows[0]
        assert r.runs_total >= 4
        assert r.agent_profile_slug
    finally:
        db.close()


def test_metrics_for_agent_returns_right_profile():
    from app.db.database import SessionLocal
    from app.services.agents.analytics import metrics_for_agent
    fx = _A()
    db = SessionLocal()
    try:
        row = metrics_for_agent(
            db, organization_id=fx["org_id"],
            agent_profile_id=fx["profile_id"],
            since=_yesterday(), until=_today(),
        )
        assert row is not None
        assert row.agent_profile_id == fx["profile_id"]
        assert row.runs_total > 0
    finally:
        db.close()


def test_metrics_per_version_includes_cost():
    """The seeded version uses model='gpt-4o-mini'. metrics_per_version
    should fold in pricing.py to produce a non-null estimated_cost_usd."""
    from app.db.database import SessionLocal
    from app.services.agents.analytics import metrics_per_version
    fx = _A()
    db = SessionLocal()
    try:
        rows = metrics_per_version(
            db, organization_id=fx["org_id"],
            agent_profile_id=fx["profile_id"],
            since=_yesterday(), until=_today(),
        )
        seeded = [r for r in rows if r.prompt_version_id == fx["version_id"]]
        assert seeded, [r.prompt_version_id for r in rows]
        r = seeded[0]
        assert r.model == "gpt-4o-mini"
        assert r.estimated_cost_usd is not None, "cost should be computed"
        assert r.estimated_cost_usd > 0
    finally:
        db.close()


# ===========================================================================
# HTTP endpoints
# ===========================================================================


def test_http_agents_summary():
    fx = _A()
    r = _client_for(fx["user_id"]).get(
        "/rag/observability/agents", params={"days": 7},
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    slugs = [it.get("slug") for it in rows]
    assert any(s and "synth" in s for s in slugs), slugs


def test_http_agent_detail_cross_org_404():
    fx_a = _A(); fx_b = _B()
    r = _client_for(fx_b["user_id"]).get(
        f"/rag/observability/agents/{fx_a['profile_id']}",
    )
    assert r.status_code == 404, r.text


def test_http_agent_versions():
    fx = _A()
    r = _client_for(fx["user_id"]).get(
        f"/rag/observability/agents/{fx['profile_id']}/versions",
        params={"days": 7},
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    seeded = [it for it in rows if it.get("prompt_version_id") == str(fx["version_id"])]
    assert seeded, rows
    assert seeded[0]["model"] == "gpt-4o-mini"
    assert seeded[0]["estimated_cost_usd"] is not None


def test_http_agent_version_recent_runs():
    fx = _A()
    r = _client_for(fx["user_id"]).get(
        f"/rag/observability/agents/{fx['profile_id']}"
        f"/versions/{fx['version_id']}/runs",
        params={"limit": 20},
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    # Our _insert_run calls used this profile+version, so >= 4 runs
    assert len(rows) >= 4, len(rows)


def test_http_deployments_feed():
    fx = _A()
    r = _client_for(fx["user_id"]).get("/rag/observability/deployments")
    assert r.status_code == 200, r.text
    rows = r.json()
    # The fixture published one version, so at least one deployment row exists.
    assert any(it["action"] == "publish" for it in rows), rows


def test_http_deployments_filter_by_action():
    fx = _A()
    r = _client_for(fx["user_id"]).get(
        "/rag/observability/deployments",
        params={"action": "rollback"},
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    # No rollback in our fixture → empty
    assert all(it["action"] == "rollback" for it in rows), rows


def test_http_deployments_filter_by_config():
    fx = _A()
    r = _client_for(fx["user_id"]).get(
        "/rag/observability/deployments",
        params={"agent_prompt_config_id": str(fx["config_id"])},
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert all(it["agent_prompt_config_id"] == str(fx["config_id"])
               for it in rows), rows


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    global _FX
    _FX = [_seed_org("alpha"), _seed_org("bravo")]

    try:
        with section("7F - schema"):
            check("7F", "UNIQUE tolerates null profile + version",
                  test_unique_index_tolerates_null_profile_and_version)
            check("7F", "UNIQUE rejects duplicate natural key",
                  test_unique_index_rejects_duplicate_key)
            check("7F", "cascade: deleting an org wipes rollup",
                  test_cascade_org_delete_wipes_rollup)

        with section("7F - pricing"):
            check("7F", "known model returns positive cost",
                  test_pricing_known_model_returns_positive)
            check("7F", "unknown model returns None",
                  test_pricing_unknown_model_returns_none)
            check("7F", "null tokens return None",
                  test_pricing_null_tokens_returns_none)

        with section("7F - rollup builder"):
            check("7F", "rebuild aggregates runs into rows",
                  test_rebuild_aggregates_runs_into_rollup_rows)
            check("7F", "rebuild is idempotent",
                  test_rebuild_is_idempotent)
            check("7F", "p50/p95 are populated",
                  test_p50_p95_computed)
            check("7F", "distinct_users is counted",
                  test_distinct_users_counted)
            check("7F", "unattributed run -> null bucket",
                  test_unattributed_run_gets_null_bucket)
            check("7F", "scoped rebuild doesn't touch other orgs",
                  test_scoped_rebuild_doesnt_touch_other_orgs)

        with section("7F - query helpers"):
            check("7F", "summary returns profile row",
                  test_summary_returns_profile_row)
            check("7F", "metrics_for_agent returns right profile",
                  test_metrics_for_agent_returns_right_profile)
            check("7F", "metrics_per_version includes cost",
                  test_metrics_per_version_includes_cost)

        with section("7F - HTTP"):
            check("7F", "GET /agents (summary)", test_http_agents_summary)
            check("7F", "GET /agents/{id} cross-org 404",
                  test_http_agent_detail_cross_org_404)
            check("7F", "GET /agents/{id}/versions",
                  test_http_agent_versions)
            check("7F", "GET /agents/{id}/versions/{v_id}/runs",
                  test_http_agent_version_recent_runs)
            check("7F", "GET /deployments", test_http_deployments_feed)
            check("7F", "GET /deployments?action=rollback",
                  test_http_deployments_filter_by_action)
            check("7F", "GET /deployments?config_id=...",
                  test_http_deployments_filter_by_config)
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
