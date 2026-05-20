"""Phase 8C ship test — sparse BehaviorProfile overrides.

This replaces the old test_phase8c.py (lineage state machine), which
goes away in 8F cleanup.

Invariants verified:

  Schema:
   1. scope_type CHECK rejects bogus values
   2. dimension CHECK rejects bogus values
   3. scope_id shape CHECK: workspace requires NULL ids,
      category/team require scope_id_int set
   4. natural-key uniqueness enforced (per-shape partial unique index)
   5. cascade: deleting an org wipes its overrides
   6. cascade: deleting a link wipes link-scoped overrides only
      (workspace-level rows survive)

  Service contract:
   7. set_override creates a new row
   8. set_override is upsert (same key -> same row, updated value)
   9. delete_override returns True if deleted, False if missing
  10. delete_override is idempotent
  11. delete_all_overrides_for_scope returns count deleted
  12. get_overrides_for_scope is sparse (only present dimensions)
  13. get_overrides_for_scope returns nested {dim: {field: value}}
  14. count_overrides_for_link / count_overrides_for_scope
  15. invalid dimension raises OverrideError
  16. invalid scope_type raises OverrideError
  17. workspace scope with scope_id raises OverrideError
  18. category scope without scope_id raises OverrideError
  19. JSONB values: string / dict / list / null all round-trip
  20. cross-org isolation: org A's overrides invisible to org B

Run with:

    venv\\Scripts\\python.exe tests\\test_phase8c_overrides.py
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
    from app.db.models import Organization, User
    db = SessionLocal()
    try:
        org = Organization(name=f"8c-{theme}-{uuid.uuid4().hex[:6]}")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"8c-{theme}",
            email=f"8c-{theme}-{uuid.uuid4()}@example.com",
            password="x", organization_id=org.id, role="org_admin",
        )
        db.add(user); db.commit(); db.refresh(user)
        return {"org_id": org.id, "user_id": user.id}
    finally:
        db.close()


def _seed_category(org_id, user_id) -> int:
    """Create a workspace Category row so we have a real scope_id_int.
    Categories require user_id (creator) per existing schema."""
    from app.db.database import SessionLocal
    from app.db.models import Category
    db = SessionLocal()
    try:
        cat = Category(
            organization_id=org_id,
            user_id=user_id,
            name=f"test-cat-{uuid.uuid4().hex[:6]}",
            description="",
        )
        db.add(cat); db.commit(); db.refresh(cat)
        return cat.id
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
            "DELETE FROM categories WHERE organization_id = :o",
            "DELETE FROM users WHERE organization_id = :o",
            "DELETE FROM organizations WHERE id = :o",
        ):
            db.execute(sql_text(stmt), {"o": str(org_id)})
        db.commit()
    finally:
        db.close()


# ===========================================================================
# Schema
# ===========================================================================


def test_scope_type_check():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import WorkspaceBehaviorOverride
    fx = _seed_org("schema-scope")
    db = SessionLocal()
    try:
        bad = WorkspaceBehaviorOverride(
            organization_id=fx["org_id"],
            scope_type="bogus", dimension="master_prompt",
            field="system", value_json="x",
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("bogus scope_type must violate CHECK")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_dimension_check():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import WorkspaceBehaviorOverride
    fx = _seed_org("schema-dim")
    db = SessionLocal()
    try:
        bad = WorkspaceBehaviorOverride(
            organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="not_a_real_dimension",
            field="", value_json="x",
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("bogus dimension must violate CHECK")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_scope_id_shape_check():
    """workspace scope must have NULL ids; category/team must have scope_id_int."""
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import WorkspaceBehaviorOverride
    fx = _seed_org("schema-shape")
    db = SessionLocal()
    try:
        # workspace with scope_id_int set -> violation
        bad = WorkspaceBehaviorOverride(
            organization_id=fx["org_id"],
            scope_type="workspace", scope_id_int=42,
            dimension="master_prompt", field="system", value_json="x",
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("workspace + scope_id_int must violate")
        except IntegrityError:
            db.rollback()
        # category without any id -> violation
        bad2 = WorkspaceBehaviorOverride(
            organization_id=fx["org_id"],
            scope_type="category", scope_id_int=None,
            dimension="master_prompt", field="system", value_json="x",
        )
        db.add(bad2)
        try:
            db.commit()
            raise AssertionError("category without scope_id must violate")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_natural_key_uniqueness():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import WorkspaceBehaviorOverride
    fx = _seed_org("schema-uniq")
    db = SessionLocal()
    try:
        a = WorkspaceBehaviorOverride(
            organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="master_prompt", field="system", value_json="A",
        )
        db.add(a); db.commit()
        b = WorkspaceBehaviorOverride(
            organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="master_prompt", field="system", value_json="B",
        )
        db.add(b)
        try:
            db.commit()
            raise AssertionError("duplicate natural key must violate")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_cascade_on_org_delete():
    """Raw SQL DELETE on organizations triggers the DB-level CASCADE.
    SQLAlchemy ORM .delete() would try to NULL out FKs first — which
    fails the NOT NULL constraint on users.organization_id."""
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal
    from app.db.models import WorkspaceBehaviorOverride
    fx = _seed_org("cascade")
    db = SessionLocal()
    try:
        ov = WorkspaceBehaviorOverride(
            organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="tone_and_personality", field="formality",
            value_json="casual",
        )
        db.add(ov); db.commit()
        # users still reference the org — wipe them first so the org delete
        # doesn't trip SQLAlchemy's ORM-side NULL propagation.
        db.execute(sql_text("DELETE FROM users WHERE organization_id = :o"),
                   {"o": str(fx["org_id"])})
        db.execute(sql_text("DELETE FROM organizations WHERE id = :o"),
                   {"o": str(fx["org_id"])})
        db.commit()
        n = db.execute(sql_text(
            "SELECT COUNT(*) FROM workspace_behavior_overrides "
            "WHERE organization_id = :o"
        ), {"o": str(fx["org_id"])}).scalar()
        assert n == 0
    finally:
        db.close()


def test_cascade_on_link_delete():
    """Deleting a workspace_template_link wipes link-scoped overrides
    but leaves workspace-scope rows untouched."""
    from app.db.database import SessionLocal
    from app.db.models import WorkspaceBehaviorOverride, WorkspaceTemplateLink
    from datetime import datetime, timezone

    fx = _seed_org("cascade-link")
    cat_id = _seed_category(fx["org_id"], fx["user_id"])
    db = SessionLocal()
    try:
        link = WorkspaceTemplateLink(
            organization_id=fx["org_id"],
            entity_type="category", entity_id_int=cat_id,
            source_template_kind="category", source_template_slug="x",
            source_template_version="1.0.0",
            provisioned_at=datetime.now(timezone.utc),
        )
        db.add(link); db.commit(); db.refresh(link)

        # category-scoped override tied to the link
        cat_ov = WorkspaceBehaviorOverride(
            organization_id=fx["org_id"],
            workspace_template_link_id=link.id,
            scope_type="category", scope_id_int=cat_id,
            dimension="output_config", field="format", value_json="markdown",
        )
        # workspace-scoped override (no link)
        ws_ov = WorkspaceBehaviorOverride(
            organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="tone_and_personality", field="formality",
            value_json="casual",
        )
        db.add_all([cat_ov, ws_ov]); db.commit()

        # Use raw SQL for the link delete — same reason as the org cascade
        # test: SQLAlchemy ORM tries to NULL FKs even when DB CASCADE
        # would handle it cleanly.
        from sqlalchemy import text as sql_text
        db.execute(sql_text("DELETE FROM workspace_template_links WHERE id = :i"),
                   {"i": link.id})
        db.commit(); db.expire_all()

        remaining = db.query(WorkspaceBehaviorOverride).filter(
            WorkspaceBehaviorOverride.organization_id == fx["org_id"],
        ).all()
        assert len(remaining) == 1, len(remaining)
        assert remaining[0].scope_type == "workspace", remaining[0].scope_type
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


# ===========================================================================
# Service contract
# ===========================================================================


def test_set_creates_row():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import set_override
    fx = _seed_org("svc-create")
    db = SessionLocal()
    try:
        row = set_override(
            db, organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="master_prompt", field="system",
            value="Be concise.",
            actor_user_id=fx["user_id"],
        )
        assert row.id is not None
        assert row.value_json == "Be concise."
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_set_is_upsert():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import (
        set_override, count_overrides_for_scope,
    )
    fx = _seed_org("svc-upsert")
    db = SessionLocal()
    try:
        first = set_override(
            db, organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="retrieval_config", field="top_k_final", value=10,
        )
        second = set_override(
            db, organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="retrieval_config", field="top_k_final", value=25,
        )
        assert first.id == second.id, "upsert must reuse the row"
        assert second.value_json == 25
        n = count_overrides_for_scope(
            db, organization_id=fx["org_id"], scope_type="workspace",
        )
        assert n == 1, n
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_delete_returns_bool():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import delete_override, set_override
    fx = _seed_org("svc-del")
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="memory_config", field="recency_weight", value=0.7,
        )
        first = delete_override(
            db, organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="memory_config", field="recency_weight",
        )
        assert first is True
        # Second call on missing row
        second = delete_override(
            db, organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="memory_config", field="recency_weight",
        )
        assert second is False
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_delete_all_for_scope_returns_count():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import (
        delete_all_overrides_for_scope, set_override,
    )
    fx = _seed_org("svc-delall")
    db = SessionLocal()
    try:
        for i, dim in enumerate([
            "master_prompt", "retrieval_config", "memory_config",
        ]):
            set_override(
                db, organization_id=fx["org_id"],
                scope_type="workspace",
                dimension=dim, field=f"field_{i}", value=str(i),
            )
        n = delete_all_overrides_for_scope(
            db, organization_id=fx["org_id"], scope_type="workspace",
        )
        assert n == 3, n
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_get_sparse_shape():
    """get_overrides_for_scope returns {dim: {field: value}};
    dimensions without rows are absent."""
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import (
        get_overrides_for_scope, set_override,
    )
    fx = _seed_org("svc-shape")
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="master_prompt", field="system", value="A",
        )
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="master_prompt", field="behavior", value="B",
        )
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="retrieval_config", field="top_k_final", value=15,
        )
        out = get_overrides_for_scope(
            db, organization_id=fx["org_id"], scope_type="workspace",
        )
        assert set(out.keys()) == {"master_prompt", "retrieval_config"}, out
        assert out["master_prompt"] == {"system": "A", "behavior": "B"}
        assert out["retrieval_config"] == {"top_k_final": 15}
        # absent dimensions
        assert "memory_config" not in out
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_count_for_link():
    """count_overrides_for_link counts only rows under that link."""
    from datetime import datetime, timezone
    from app.db.database import SessionLocal
    from app.db.models import WorkspaceTemplateLink
    from app.services.behavior.overrides import (
        count_overrides_for_link, set_override,
    )
    fx = _seed_org("svc-cntlink")
    cat_id = _seed_category(fx["org_id"], fx["user_id"])
    db = SessionLocal()
    try:
        link = WorkspaceTemplateLink(
            organization_id=fx["org_id"],
            entity_type="category", entity_id_int=cat_id,
            source_template_kind="category", source_template_slug="x",
            source_template_version="1.0.0",
            provisioned_at=datetime.now(timezone.utc),
        )
        db.add(link); db.commit(); db.refresh(link)
        for i, dim in enumerate(["master_prompt", "retrieval_config"]):
            set_override(
                db, organization_id=fx["org_id"],
                scope_type="category", scope_id=cat_id,
                workspace_template_link_id=link.id,
                dimension=dim, field=f"f{i}", value=str(i),
            )
        # Workspace-level override (no link) — should NOT count
        set_override(
            db, organization_id=fx["org_id"],
            scope_type="workspace",
            dimension="tone_and_personality", field="formality",
            value="casual",
        )
        n = count_overrides_for_link(db, link_id=link.id)
        assert n == 2, n
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


# ===========================================================================
# Validation
# ===========================================================================


def test_invalid_dimension_raises():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import OverrideError, set_override
    fx = _seed_org("vld-dim")
    db = SessionLocal()
    try:
        try:
            set_override(
                db, organization_id=fx["org_id"],
                scope_type="workspace",
                dimension="not_real", field="x", value=1,
            )
            raise AssertionError("must raise")
        except OverrideError:
            pass
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_invalid_scope_type_raises():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import OverrideError, set_override
    fx = _seed_org("vld-scope")
    db = SessionLocal()
    try:
        try:
            set_override(
                db, organization_id=fx["org_id"],
                scope_type="meeting",  # not in {workspace, category, team}
                dimension="master_prompt", field="system", value="x",
            )
            raise AssertionError("must raise")
        except OverrideError:
            pass
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_workspace_scope_rejects_scope_id():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import OverrideError, set_override
    fx = _seed_org("vld-wsid")
    db = SessionLocal()
    try:
        try:
            set_override(
                db, organization_id=fx["org_id"],
                scope_type="workspace", scope_id=42,
                dimension="master_prompt", field="system", value="x",
            )
            raise AssertionError("must raise")
        except OverrideError:
            pass
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_category_scope_requires_scope_id():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import OverrideError, set_override
    fx = _seed_org("vld-catid")
    db = SessionLocal()
    try:
        try:
            set_override(
                db, organization_id=fx["org_id"],
                scope_type="category",  # no scope_id
                dimension="master_prompt", field="system", value="x",
            )
            raise AssertionError("must raise")
        except OverrideError:
            pass
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


# ===========================================================================
# JSONB round-trip + cross-org
# ===========================================================================


def test_jsonb_value_shapes_roundtrip():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import (
        get_overrides_for_scope, set_override,
    )
    fx = _seed_org("jsonb")
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"], scope_type="workspace",
            dimension="master_prompt", field="system", value="a string",
        )
        set_override(
            db, organization_id=fx["org_id"], scope_type="workspace",
            dimension="enabled_agents", field="",
            value=["planner", "extractor"],
        )
        set_override(
            db, organization_id=fx["org_id"], scope_type="workspace",
            dimension="retrieval_config", field="",
            value={"top_k": 25, "rerank": "cohere"},
        )
        set_override(
            db, organization_id=fx["org_id"], scope_type="workspace",
            dimension="evaluation_rules", field="threshold", value=0.85,
        )
        out = get_overrides_for_scope(
            db, organization_id=fx["org_id"], scope_type="workspace",
        )
        assert out["master_prompt"]["system"] == "a string"
        assert out["enabled_agents"][""] == ["planner", "extractor"]
        assert out["retrieval_config"][""] == {"top_k": 25, "rerank": "cohere"}
        assert out["evaluation_rules"]["threshold"] == 0.85
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_cross_org_isolation():
    from app.db.database import SessionLocal
    from app.services.behavior.overrides import (
        get_overrides_for_scope, set_override,
    )
    fx_a = _seed_org("xorg-a")
    fx_b = _seed_org("xorg-b")
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx_a["org_id"], scope_type="workspace",
            dimension="master_prompt", field="system",
            value="org-A private system prompt",
        )
        b_overrides = get_overrides_for_scope(
            db, organization_id=fx_b["org_id"], scope_type="workspace",
        )
        assert b_overrides == {}, b_overrides
        a_overrides = get_overrides_for_scope(
            db, organization_id=fx_a["org_id"], scope_type="workspace",
        )
        assert "master_prompt" in a_overrides
    finally:
        db.close()
        _cleanup_org(fx_a["org_id"])
        _cleanup_org(fx_b["org_id"])


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        with section("8C - schema"):
            check("8C", "scope_type CHECK", test_scope_type_check)
            check("8C", "dimension CHECK", test_dimension_check)
            check("8C", "scope_id shape CHECK", test_scope_id_shape_check)
            check("8C", "natural-key UNIQUE", test_natural_key_uniqueness)
            check("8C", "cascade on org delete", test_cascade_on_org_delete)
            check("8C", "cascade on link delete", test_cascade_on_link_delete)

        with section("8C - service contract"):
            check("8C", "set creates row", test_set_creates_row)
            check("8C", "set is upsert", test_set_is_upsert)
            check("8C", "delete returns bool", test_delete_returns_bool)
            check("8C", "delete_all_for_scope returns count",
                  test_delete_all_for_scope_returns_count)
            check("8C", "get sparse shape", test_get_sparse_shape)
            check("8C", "count_for_link narrows correctly",
                  test_count_for_link)

        with section("8C - validation"):
            check("8C", "invalid dimension raises",
                  test_invalid_dimension_raises)
            check("8C", "invalid scope_type raises",
                  test_invalid_scope_type_raises)
            check("8C", "workspace + scope_id raises",
                  test_workspace_scope_rejects_scope_id)
            check("8C", "category without scope_id raises",
                  test_category_scope_requires_scope_id)

        with section("8C - JSONB + cross-org"):
            check("8C", "jsonb shapes roundtrip",
                  test_jsonb_value_shapes_roundtrip)
            check("8C", "cross-org isolation", test_cross_org_isolation)
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
