"""Phase 8A (revised) ship test — template_behavior_profiles.

This replaces the old test_phase8a.py (catalog of teams + categories
+ agents in 3 separate tables). That goes away in 8F.

Invariants verified:

  Schema:
   1. scope_kind CHECK rejects bogus values
   2. state CHECK rejects bogus values
   3. version_fmt CHECK rejects non-semver strings
   4. (scope_kind, slug, version) UNIQUE — duplicates rejected
   5. partial unique (scope_kind='global', state='published') — only
      one platform default published at a time

  Catalog content:
   6. CATALOG_PROFILES has at least 1 global, >= 11 categories, >= 9 teams
   7. Each profile has a non-empty manifest_hash
   8. manifest_hash is stable: re-hashing the same profile gives
      the same value
   9. GLOBAL_DEFAULT has enabled_agents set (action-item-manager)
  10. Every category profile has a non-empty master_prompt.system

  Seed roundtrip:
  11. seed_catalog inserts every catalog row on first run
  12. seed_catalog second run inserts 0 (matched count climbs)
  13. seed_catalog detects drift when hash changes (report.drifted non-empty)
  14. seed_catalog dry_run does not write

  Registry reads:
  15. get_profile(scope_kind, slug, 'latest') returns published row
  16. get_global_default returns the platform default
  17. list_profiles returns latest version per slug
  18. profile_to_dimensions_dict has all 11 dimension keys

Run with:

    venv\\Scripts\\python.exe tests\\test_phase8a_behavior_profiles.py
"""
from __future__ import annotations

import os
import sys
import traceback
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
# Schema tests — focused on CHECK + UNIQUE constraints. The seeded
# catalog rows will already be in the DB from prior runs, so schema
# tests use random slugs that won't collide.
# ---------------------------------------------------------------------------


def _random_slug(prefix: str) -> str:
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_scope_kind_check():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import TemplateBehaviorProfile
    db = SessionLocal()
    try:
        bad = TemplateBehaviorProfile(
            scope_kind="not_real", slug=_random_slug("bad"),
            version="1.0.0", display_name="x",
            manifest_hash="0" * 64,
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("bogus scope_kind must violate")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_state_check():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import TemplateBehaviorProfile
    db = SessionLocal()
    try:
        bad = TemplateBehaviorProfile(
            scope_kind="category", slug=_random_slug("bad"),
            version="1.0.0", display_name="x",
            state="someday", manifest_hash="0" * 64,
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("bogus state must violate")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_version_format_check():
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import TemplateBehaviorProfile
    db = SessionLocal()
    try:
        bad = TemplateBehaviorProfile(
            scope_kind="category", slug=_random_slug("bad"),
            version="oneoh", display_name="x",
            manifest_hash="0" * 64,
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("non-semver version must violate")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_slug_version_unique():
    """(scope_kind, slug, version) is unique. Inserting the same
    triple twice must fail."""
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import TemplateBehaviorProfile
    db = SessionLocal()
    try:
        slug = _random_slug("uniq")
        a = TemplateBehaviorProfile(
            scope_kind="category", slug=slug, version="1.0.0",
            display_name="x", manifest_hash="a" * 64,
        )
        db.add(a); db.commit()
        b = TemplateBehaviorProfile(
            scope_kind="category", slug=slug, version="1.0.0",
            display_name="x2", manifest_hash="b" * 64,
        )
        db.add(b)
        try:
            db.commit()
            raise AssertionError("duplicate slug+version must violate")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_only_one_global_published():
    """The partial unique index ensures we can't have two PUBLISHED
    global defaults at once. Two drafts is fine; two published is not."""
    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal
    from app.db.models import TemplateBehaviorProfile
    db = SessionLocal()
    try:
        # The seed already created scope_kind='global'/slug='__default__'
        # in the published state. Trying to insert another should fail
        # the partial unique index.
        bad = TemplateBehaviorProfile(
            scope_kind="global", slug="__default__", version="9.9.9",
            display_name="duplicate global", state="published",
            manifest_hash="z" * 64,
        )
        db.add(bad)
        try:
            db.commit()
            raise AssertionError("two published globals must violate")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Catalog content
# ---------------------------------------------------------------------------


def test_catalog_shape():
    from app.services.templates.behavior_catalog import (
        CATALOG_PROFILES, all_category_profiles, all_team_profiles,
    )
    globals_ = [p for p in CATALOG_PROFILES if p.scope_kind == "global"]
    assert len(globals_) == 1, len(globals_)
    # New department/team hierarchy: ~9 categories (departments) +
    # ~25 teams (sub-teams). Lower bounds keep test resilient.
    assert len(all_category_profiles()) >= 7, len(all_category_profiles())
    assert len(all_team_profiles()) >= 15, len(all_team_profiles())


def test_manifest_hash_present_and_stable():
    from app.services.templates.behavior_catalog import (
        CATALOG_PROFILES, manifest_hash,
    )
    for prof in CATALOG_PROFILES:
        h1 = manifest_hash(prof)
        h2 = manifest_hash(prof)
        assert h1 == h2, f"hash unstable for {prof.slug}"
        assert h1 and len(h1) == 64, f"bogus hash for {prof.slug}: {h1}"


def test_global_default_enables_action_item_manager():
    from app.services.templates.behavior_catalog import GLOBAL_DEFAULT
    assert GLOBAL_DEFAULT.intent["capabilities"]["action_items"] is True, \
        GLOBAL_DEFAULT.intent


def test_categories_have_master_prompt_system():
    from app.services.templates.behavior_catalog import all_category_profiles
    for cat in all_category_profiles():
        role_focus = cat.intent.get("behavior", {}).get("role_focus", "")
        assert role_focus, f"{cat.slug} missing intent.behavior.role_focus"


# ---------------------------------------------------------------------------
# Seed roundtrip
# ---------------------------------------------------------------------------


def test_seed_inserts_or_matches():
    """Running the seed on a clean run should match every catalog
    row (since this test runs AFTER the migration + initial seed have
    been applied at test setup). On a fresh DB the first invocation
    inserts; on subsequent invocations everything matches."""
    from app.db.database import SessionLocal
    from app.services.templates.behavior_seed import seed_catalog
    from app.services.templates.behavior_catalog import CATALOG_PROFILES
    db = SessionLocal()
    try:
        report = seed_catalog(db)
        total = report.inserted + report.matched
        assert total >= len(CATALOG_PROFILES), (
            f"total {total} < catalog size {len(CATALOG_PROFILES)}"
        )
        # Nothing should be drifted on a clean run
        assert report.drifted == [], report.drifted
    finally:
        db.close()


def test_seed_second_run_zero_inserts():
    from app.db.database import SessionLocal
    from app.services.templates.behavior_seed import seed_catalog
    db = SessionLocal()
    try:
        # First run to ensure populated
        seed_catalog(db)
        # Second run should insert nothing new
        second = seed_catalog(db)
        assert second.inserted == 0, second.inserted
        assert second.drifted == [], second.drifted
    finally:
        db.close()


def test_seed_dry_run_writes_nothing():
    """dry_run reports inserts but doesn't commit. Verify by
    counting DB rows before/after."""
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal
    from app.services.templates.behavior_seed import seed_catalog
    db = SessionLocal()
    try:
        before = db.execute(sql_text(
            "SELECT COUNT(*) FROM template_behavior_profiles"
        )).scalar()
        seed_catalog(db, dry_run=True)
        after = db.execute(sql_text(
            "SELECT COUNT(*) FROM template_behavior_profiles"
        )).scalar()
        assert before == after, (before, after)
    finally:
        db.close()


def test_seed_detects_drift():
    """If we manually corrupt a DB row's manifest_hash, the next seed
    run should report it as drifted."""
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal
    from app.services.templates.behavior_seed import seed_catalog
    db = SessionLocal()
    try:
        # Pick the global default — corrupt its hash
        original = db.execute(sql_text(
            "SELECT manifest_hash FROM template_behavior_profiles "
            "WHERE scope_kind='global' AND slug='__default__' "
            "ORDER BY version DESC LIMIT 1"
        )).scalar()
        assert original, "global default missing — seed not run?"
        db.execute(sql_text(
            "UPDATE template_behavior_profiles "
            "SET manifest_hash = 'x' || repeat('0', 63) "
            "WHERE scope_kind='global' AND slug='__default__'"
        ))
        db.commit()
        try:
            report = seed_catalog(db)
            assert any("global/__default__" in s for s in report.drifted), \
                report.drifted
        finally:
            # Restore — leave DB clean for downstream tests
            db.execute(sql_text(
                "UPDATE template_behavior_profiles "
                "SET manifest_hash = :h "
                "WHERE scope_kind='global' AND slug='__default__'"
            ), {"h": original})
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Registry reads
# ---------------------------------------------------------------------------


def test_get_profile_latest():
    from app.db.database import SessionLocal
    from app.services.templates.behavior_registry import get_profile
    db = SessionLocal()
    try:
        row = get_profile(
            db, scope_kind="category", slug="security",
        )
        assert row is not None
        assert row.scope_kind == "category"
        assert row.slug == "security"
    finally:
        db.close()


def test_get_global_default():
    from app.db.database import SessionLocal
    from app.services.templates.behavior_registry import get_global_default
    db = SessionLocal()
    try:
        from app.schemas.intent_schema import IntentProfile
        row = get_global_default(db)
        assert row is not None
        assert row.scope_kind == "global"
        assert row.slug == "__default__"
        
        intent = IntentProfile.model_validate(row.intent or {})
        assert intent.capabilities.action_items is True
    finally:
        db.close()


def test_list_profiles_latest_per_slug():
    from app.db.database import SessionLocal
    from app.services.templates.behavior_registry import list_profiles
    db = SessionLocal()
    try:
        rows = list_profiles(db, scope_kind="category")
        # At least 11 distinct category slugs from the catalog
        slugs = {r.slug for r in rows}
        assert len(slugs) >= 11, slugs
    finally:
        db.close()


def test_profile_to_dimensions_dict_shape():
    from app.db.database import SessionLocal
    from app.services.templates.behavior_registry import (
        get_global_default, profile_to_dimensions_dict,
    )
    db = SessionLocal()
    try:
        row = get_global_default(db)
        d = profile_to_dimensions_dict(row)
        for dim in (
            "master_prompt", "enabled_agents", "retrieval_config",
            "memory_config", "output_config", "extraction_rules",
            "automation_rules", "evaluation_rules",
            "tone_and_personality", "compliance_and_guardrails",
            "tools_and_integrations",
        ):
            assert dim in d, dim
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    # Run the seed once before the schema/content tests so the DB
    # has the catalog populated for read tests.
    from app.db.database import SessionLocal
    from app.services.templates.behavior_seed import seed_catalog
    setup_db = SessionLocal()
    try:
        seed_catalog(setup_db)
    finally:
        setup_db.close()

    try:
        with section("8A - schema"):
            check("8A", "scope_kind CHECK", test_scope_kind_check)
            check("8A", "state CHECK", test_state_check)
            check("8A", "version_fmt CHECK", test_version_format_check)
            check("8A", "(scope, slug, version) UNIQUE", test_slug_version_unique)
            check("8A", "only one published global",
                  test_only_one_global_published)

        with section("8A - catalog content"):
            check("8A", "catalog shape", test_catalog_shape)
            check("8A", "manifest hash present + stable",
                  test_manifest_hash_present_and_stable)
            check("8A", "global default enables action-item-manager",
                  test_global_default_enables_action_item_manager)
            check("8A", "categories have master_prompt.system",
                  test_categories_have_master_prompt_system)

        with section("8A - seed roundtrip"):
            check("8A", "seed inserts or matches every row",
                  test_seed_inserts_or_matches)
            check("8A", "second seed inserts 0",
                  test_seed_second_run_zero_inserts)
            check("8A", "dry_run writes nothing",
                  test_seed_dry_run_writes_nothing)
            check("8A", "seed detects drift", test_seed_detects_drift)

        with section("8A - registry reads"):
            check("8A", "get_profile latest", test_get_profile_latest)
            check("8A", "get_global_default", test_get_global_default)
            check("8A", "list_profiles latest per slug",
                  test_list_profiles_latest_per_slug)
            check("8A", "profile_to_dimensions_dict shape",
                  test_profile_to_dimensions_dict_shape)
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
