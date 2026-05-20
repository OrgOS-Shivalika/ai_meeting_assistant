"""Phase 8E ship test — behavior orchestration HTTP API.

Covers the Agent Control dashboard's backend contract:

  GET /behavior/scopes:
   1. empty workspace returns zero counts + empty lists
   2. after install, categories[]/teams[] list installed scopes
   3. override counts surface per-scope
   4. cross-org isolation

  GET /behavior/resolve:
   5. no scope ids -> global default only
   6. with category_id (installed) -> resolved profile contains
      category template's enabled_agents
   7. trace[] reflects each contributing layer
   8. category_id from another org returns 404

  GET /behavior/overrides:
   9. returns sparse {dim: {field: value}}
  10. count equals total override rows
  11. invalid scope shape -> 400

  PUT /behavior/overrides:
  12. creates an override row
  13. is upsert (same key returns same id, new value)
  14. unknown dimension -> 400
  15. viewer -> 403
  16. cross-org scope_id -> 404

  DELETE /behavior/overrides (single):
  17. removes one override (returns {deleted: true})
  18. missing key returns {deleted: false}

  DELETE /behavior/overrides/scope (reset):
  19. wipes all overrides for one scope; returns count
  20. workspace-level wipe leaves category-level untouched

Run with:

    venv\\Scripts\\python.exe tests\\test_phase8e_behavior_api.py
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


def _seed_org(theme: str, *, role: str = "org_admin") -> dict:
    from app.db.database import SessionLocal
    from app.db.models import Organization, User
    db = SessionLocal()
    try:
        org = Organization(name=f"8e-{theme}-{uuid.uuid4().hex[:6]}")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"8e-{theme}",
            email=f"8e-{theme}-{uuid.uuid4()}@example.com",
            password="x", organization_id=org.id, role=role,
        )
        db.add(user); db.commit(); db.refresh(user)
        return {"org_id": org.id, "user_id": user.id}
    finally:
        db.close()


def _install_profile(org_id, user_id, scope_kind, slug):
    from app.db.database import SessionLocal
    from app.services.behavior.provisioning import install_profile
    db = SessionLocal()
    try:
        link, _ = install_profile(
            db, organization_id=org_id, user_id=user_id,
            scope_kind=scope_kind, slug=slug,
        )
        return link.id, link.entity_id_int
    finally:
        db.close()


def _ensure_seed():
    from app.db.database import SessionLocal
    from app.services.templates.behavior_seed import seed_catalog
    db = SessionLocal()
    try:
        seed_catalog(db)
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
            "DELETE FROM template_provisioning_jobs WHERE organization_id = :o",
            "DELETE FROM categories WHERE organization_id = :o",
            "DELETE FROM users WHERE organization_id = :o",
            "DELETE FROM organizations WHERE id = :o",
        ):
            db.execute(sql_text(stmt), {"o": str(org_id)})
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


# ===========================================================================
# GET /behavior/scopes
# ===========================================================================


def test_scopes_empty_workspace():
    _ensure_seed()
    fx = _seed_org("scopes-empty")
    try:
        r = _client_for(fx["user_id"]).get("/behavior/scopes")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["workspace_overrides_count"] == 0
        assert body["categories"] == []
        assert body["teams"] == []
    finally:
        _cleanup_org(fx["org_id"])


def test_scopes_lists_installed():
    _ensure_seed()
    fx = _seed_org("scopes-lists")
    _install_profile(fx["org_id"], fx["user_id"], "category", "security")
    # Install a team — parent category (security) auto-installs via the
    # team-needs-parent flow in provisioning. After: 1 category +
    # 1 team. (The first install already created 'security' as the
    # category, so the team's parent-resolver finds it.)
    _install_profile(fx["org_id"], fx["user_id"], "team", "security-engineering")
    try:
        body = _client_for(fx["user_id"]).get("/behavior/scopes").json()
        assert len(body["categories"]) == 1, body
        assert len(body["teams"]) == 1, body
        assert body["categories"][0]["template_slug"] == "security"
        assert body["teams"][0]["template_slug"] == "security-engineering"
    finally:
        _cleanup_org(fx["org_id"])


def test_scopes_override_counts():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import set_override
    _ensure_seed()
    fx = _seed_org("scopes-counts")
    _, cat_id = _install_profile(
        fx["org_id"], fx["user_id"], "category", "sales",
    )
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="category", scope_id=cat_id,
            dimension="master_prompt", field="behavior", value="X",
        )
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="tone_and_personality", field="formality", value="terse",
        )
    finally:
        db.close()
    try:
        body = _client_for(fx["user_id"]).get("/behavior/scopes").json()
        assert body["workspace_overrides_count"] == 1, body
        cat = next(c for c in body["categories"] if c["id"] == cat_id)
        assert cat["override_count"] == 1, cat
    finally:
        _cleanup_org(fx["org_id"])


def test_scopes_cross_org_isolation():
    _ensure_seed()
    fx_a = _seed_org("scopes-x-a")
    fx_b = _seed_org("scopes-x-b")
    _install_profile(fx_a["org_id"], fx_a["user_id"], "category", "executive")
    try:
        body_a = _client_for(fx_a["user_id"]).get("/behavior/scopes").json()
        body_b = _client_for(fx_b["user_id"]).get("/behavior/scopes").json()
        assert len(body_a["categories"]) == 1
        assert len(body_b["categories"]) == 0
    finally:
        _cleanup_org(fx_a["org_id"])
        _cleanup_org(fx_b["org_id"])


# ===========================================================================
# GET /behavior/resolve
# ===========================================================================


def test_resolve_no_scope_returns_global():
    _ensure_seed()
    fx = _seed_org("resolve-empty")
    try:
        body = _client_for(fx["user_id"]).get("/behavior/resolve").json()
        assert "action-item-manager" in body["enabled_agents"]
        layers = [t["layer"] for t in body["trace"]]
        assert layers == ["global"], layers
    finally:
        _cleanup_org(fx["org_id"])


def test_resolve_with_category():
    _ensure_seed()
    fx = _seed_org("resolve-cat")
    _, cat_id = _install_profile(
        fx["org_id"], fx["user_id"], "category", "security",
    )
    try:
        body = _client_for(fx["user_id"]).get(
            "/behavior/resolve", params={"category_id": cat_id},
        ).json()
        assert "incident-investigator" in body["enabled_agents"], body["enabled_agents"]
        layers = [t["layer"] for t in body["trace"]]
        assert "category_template" in layers
    finally:
        _cleanup_org(fx["org_id"])


def test_resolve_cross_org_scope_404():
    _ensure_seed()
    fx_a = _seed_org("resolve-x-a")
    fx_b = _seed_org("resolve-x-b")
    _, cat_id_a = _install_profile(
        fx_a["org_id"], fx_a["user_id"], "category", "hr",
    )
    try:
        r = _client_for(fx_b["user_id"]).get(
            "/behavior/resolve", params={"category_id": cat_id_a},
        )
        assert r.status_code == 404, r.text
    finally:
        _cleanup_org(fx_a["org_id"])
        _cleanup_org(fx_b["org_id"])


# ===========================================================================
# GET /behavior/overrides
# ===========================================================================


def test_overrides_get_returns_sparse():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import set_override
    _ensure_seed()
    fx = _seed_org("get-ov")
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"], scope_type="workspace",
            dimension="master_prompt", field="system", value="A",
        )
        set_override(
            db, organization_id=fx["org_id"], scope_type="workspace",
            dimension="memory_config", field="recency_weight", value=0.9,
        )
    finally:
        db.close()
    try:
        body = _client_for(fx["user_id"]).get(
            "/behavior/overrides", params={"scope_type": "workspace"},
        ).json()
        assert body["count"] == 2, body
        assert body["overrides"]["master_prompt"]["system"] == "A"
        assert body["overrides"]["memory_config"]["recency_weight"] == 0.9
    finally:
        _cleanup_org(fx["org_id"])


def test_overrides_get_invalid_scope_shape_400():
    _ensure_seed()
    fx = _seed_org("get-ov-bad")
    try:
        # workspace + scope_id
        r = _client_for(fx["user_id"]).get(
            "/behavior/overrides",
            params={"scope_type": "workspace", "scope_id": 42},
        )
        assert r.status_code == 400, r.text
        # category without scope_id
        r2 = _client_for(fx["user_id"]).get(
            "/behavior/overrides", params={"scope_type": "category"},
        )
        assert r2.status_code == 400, r2.text
    finally:
        _cleanup_org(fx["org_id"])


# ===========================================================================
# PUT /behavior/overrides
# ===========================================================================


def test_put_override_creates():
    _ensure_seed()
    fx = _seed_org("put-create")
    try:
        r = _client_for(fx["user_id"]).put(
            "/behavior/overrides",
            json={
                "scope_type": "workspace",
                "dimension": "tone_and_personality",
                "field": "formality", "value": "terse",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["value"] == "terse"
        assert body["scope_type"] == "workspace"
    finally:
        _cleanup_org(fx["org_id"])


def test_put_override_upsert():
    _ensure_seed()
    fx = _seed_org("put-upsert")
    client = _client_for(fx["user_id"])
    try:
        a = client.put("/behavior/overrides", json={
            "scope_type": "workspace",
            "dimension": "retrieval_config",
            "field": "top_k_final", "value": 10,
        }).json()
        b = client.put("/behavior/overrides", json={
            "scope_type": "workspace",
            "dimension": "retrieval_config",
            "field": "top_k_final", "value": 25,
        }).json()
        assert a["id"] == b["id"], (a, b)
        assert b["value"] == 25
    finally:
        _cleanup_org(fx["org_id"])


def test_put_override_unknown_dimension_400():
    _ensure_seed()
    fx = _seed_org("put-bad-dim")
    try:
        r = _client_for(fx["user_id"]).put(
            "/behavior/overrides",
            json={
                "scope_type": "workspace",
                "dimension": "not_a_real_dim",
                "field": "x", "value": 1,
            },
        )
        assert r.status_code == 400, r.text
    finally:
        _cleanup_org(fx["org_id"])


def test_put_override_viewer_403():
    _ensure_seed()
    fx = _seed_org("put-viewer", role="viewer")
    try:
        r = _client_for(fx["user_id"]).put(
            "/behavior/overrides",
            json={
                "scope_type": "workspace",
                "dimension": "tone_and_personality",
                "field": "formality", "value": "terse",
            },
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup_org(fx["org_id"])


def test_put_override_cross_org_scope_404():
    _ensure_seed()
    fx_a = _seed_org("put-x-a")
    fx_b = _seed_org("put-x-b")
    _, cat_id_a = _install_profile(
        fx_a["org_id"], fx_a["user_id"], "category", "sales",
    )
    try:
        r = _client_for(fx_b["user_id"]).put(
            "/behavior/overrides",
            json={
                "scope_type": "category", "scope_id": cat_id_a,
                "dimension": "master_prompt", "field": "behavior", "value": "X",
            },
        )
        assert r.status_code == 404, r.text
    finally:
        _cleanup_org(fx_a["org_id"])
        _cleanup_org(fx_b["org_id"])


# ===========================================================================
# DELETE /behavior/overrides (single)
# ===========================================================================


def test_delete_single_returns_bool():
    _ensure_seed()
    fx = _seed_org("del-single")
    client = _client_for(fx["user_id"])
    try:
        client.put("/behavior/overrides", json={
            "scope_type": "workspace",
            "dimension": "master_prompt", "field": "system", "value": "x",
        })
        r1 = client.delete(
            "/behavior/overrides",
            params={
                "scope_type": "workspace",
                "dimension": "master_prompt", "field": "system",
            },
        )
        assert r1.json()["deleted"] is True
        r2 = client.delete(
            "/behavior/overrides",
            params={
                "scope_type": "workspace",
                "dimension": "master_prompt", "field": "system",
            },
        )
        assert r2.json()["deleted"] is False
    finally:
        _cleanup_org(fx["org_id"])


# ===========================================================================
# DELETE /behavior/overrides/scope (reset)
# ===========================================================================


def test_reset_scope_wipes_all_overrides():
    _ensure_seed()
    fx = _seed_org("reset-scope")
    client = _client_for(fx["user_id"])
    try:
        # Three overrides at workspace scope
        for dim, fld in (
            ("master_prompt", "system"),
            ("master_prompt", "behavior"),
            ("retrieval_config", "top_k_final"),
        ):
            client.put("/behavior/overrides", json={
                "scope_type": "workspace",
                "dimension": dim, "field": fld, "value": "x",
            })
        r = client.delete(
            "/behavior/overrides/scope",
            params={"scope_type": "workspace"},
        )
        assert r.json()["deleted_count"] == 3, r.json()
    finally:
        _cleanup_org(fx["org_id"])


def test_reset_one_scope_leaves_others_untouched():
    _ensure_seed()
    fx = _seed_org("reset-isolated")
    client = _client_for(fx["user_id"])
    _, cat_id = _install_profile(
        fx["org_id"], fx["user_id"], "category", "executive",
    )
    try:
        client.put("/behavior/overrides", json={
            "scope_type": "workspace",
            "dimension": "tone_and_personality", "field": "formality",
            "value": "terse",
        })
        client.put("/behavior/overrides", json={
            "scope_type": "category", "scope_id": cat_id,
            "dimension": "master_prompt", "field": "system", "value": "Y",
        })
        # Reset only workspace scope
        r = client.delete(
            "/behavior/overrides/scope",
            params={"scope_type": "workspace"},
        )
        assert r.json()["deleted_count"] == 1
        # Category override survives
        cat = client.get(
            "/behavior/overrides",
            params={"scope_type": "category", "scope_id": cat_id},
        ).json()
        assert cat["count"] == 1, cat
    finally:
        _cleanup_org(fx["org_id"])


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        with section("8E - /scopes"):
            check("8E", "empty workspace", test_scopes_empty_workspace)
            check("8E", "lists installed", test_scopes_lists_installed)
            check("8E", "override counts surface", test_scopes_override_counts)
            check("8E", "cross-org isolation",
                  test_scopes_cross_org_isolation)

        with section("8E - /resolve"):
            check("8E", "no scope -> global only",
                  test_resolve_no_scope_returns_global)
            check("8E", "with category", test_resolve_with_category)
            check("8E", "cross-org scope -> 404",
                  test_resolve_cross_org_scope_404)

        with section("8E - GET /overrides"):
            check("8E", "returns sparse shape", test_overrides_get_returns_sparse)
            check("8E", "invalid scope shape -> 400",
                  test_overrides_get_invalid_scope_shape_400)

        with section("8E - PUT /overrides"):
            check("8E", "creates row", test_put_override_creates)
            check("8E", "upsert", test_put_override_upsert)
            check("8E", "unknown dimension -> 400",
                  test_put_override_unknown_dimension_400)
            check("8E", "viewer -> 403", test_put_override_viewer_403)
            check("8E", "cross-org scope -> 404",
                  test_put_override_cross_org_scope_404)

        with section("8E - DELETE /overrides"):
            check("8E", "single returns bool", test_delete_single_returns_bool)

        with section("8E - DELETE /overrides/scope"):
            check("8E", "wipes all in scope",
                  test_reset_scope_wipes_all_overrides)
            check("8E", "one scope isolated",
                  test_reset_one_scope_leaves_others_untouched)
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
