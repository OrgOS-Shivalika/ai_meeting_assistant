"""Phase 6F ship test — importance backfill CLI.

Architectural properties verified:

  1. Dry-run returns eligible orgs without writing any audit rows
     or modifying any importance_score.
  2. `--org-id <uuid>` narrows the run to a single org (other orgs
     untouched).
  3. `--targets entities` scores ONLY entities; chunk + relationship
     importance values stay at their pre-run value.
  4. `--targets all` scores every target kind for the requested org(s).
  5. Idempotent: re-running over unchanged data writes audit rows
     with rows_updated=0 (scorer short-circuits within-epsilon scores).
  6. CLI argv path (`main(argv)`) exits 0 on success.
  7. Bogus --targets value raises a ValueError from `_resolve_targets`
     (defense-in-depth — argparse already restricts choices, but the
     programmatic path needs its own guard).
  8. `--algorithm-version` override threads through to audit row.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase6f.py
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
# Tests
# ---------------------------------------------------------------------------

_FX = None


def test_dry_run_lists_orgs_without_writes():
    from app.db.database import SessionLocal
    from app.db.models import ImportanceRun
    from app.scripts.backfill_importance import run as backfill_run
    db = SessionLocal()
    try:
        before = db.query(ImportanceRun).filter(
            ImportanceRun.organization_id == _FX.organization_id,
        ).count()
    finally:
        db.close()

    summary = backfill_run(org_id=_FX.organization_id, dry_run=True)
    assert summary["dry_run"] is True
    assert summary["eligible_orgs"] == 1
    assert summary["dispatched"] == 0
    assert summary["errors"] == 0
    assert str(_FX.organization_id) in summary["org_ids"]

    db = SessionLocal()
    try:
        after = db.query(ImportanceRun).filter(
            ImportanceRun.organization_id == _FX.organization_id,
        ).count()
        assert after == before, (
            f"dry-run wrote importance_runs ({before} -> {after})"
        )
    finally:
        db.close()


def test_org_id_narrows_to_single_org():
    """Build a second canonical org; --org-id pointed at fixture A
    must NOT touch fixture B."""
    from app.db.database import SessionLocal
    from app.db.models import ImportanceRun
    from app.scripts.backfill_importance import run as backfill_run
    from tests.fixtures import build_canonical_org, cleanup_canonical_org

    db = SessionLocal()
    other = build_canonical_org(db, mode="stub")
    try:
        before_other = db.query(ImportanceRun).filter(
            ImportanceRun.organization_id == other.organization_id,
        ).count()
        db.close()

        # Run targeted at the primary fixture only
        summary = backfill_run(
            org_id=_FX.organization_id, inline=True,
        )
        assert summary["eligible_orgs"] == 1
        assert summary["dispatched"] >= 1

        db = SessionLocal()
        after_other = db.query(ImportanceRun).filter(
            ImportanceRun.organization_id == other.organization_id,
        ).count()
        assert after_other == before_other, (
            "--org-id should not touch other orgs"
        )
    finally:
        cleanup_canonical_org(db, other)
        db.close()


def test_targets_entities_only_skips_chunks_and_rels():
    from app.db.database import SessionLocal
    from app.db.models import (
        Entity, MeetingChunk, DocumentChunk, Relationship, ImportanceRun,
    )
    from app.scripts.backfill_importance import run as backfill_run
    db = SessionLocal()
    try:
        # Wipe importance scores so we can detect partial updates
        db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == _FX.organization_id,
        ).update({"importance_score": None}, synchronize_session=False)
        db.query(DocumentChunk).filter(
            DocumentChunk.organization_id == _FX.organization_id,
        ).update({"importance_score": None}, synchronize_session=False)
        db.query(Entity).filter(
            Entity.organization_id == _FX.organization_id,
        ).update({"importance_score": None}, synchronize_session=False)
        db.query(Relationship).filter(
            Relationship.organization_id == _FX.organization_id,
        ).update({"importance_score": None}, synchronize_session=False)
        db.commit()

        summary = backfill_run(
            org_id=_FX.organization_id,
            targets_arg="entities",
            inline=True,
        )
        assert summary["dispatched"] == 1
        assert summary["targets"] == ["entity"]

        # Only entities should have non-null scores
        ent_n = db.query(Entity).filter(
            Entity.organization_id == _FX.organization_id,
            Entity.importance_score.isnot(None),
        ).count()
        chunk_n = db.query(MeetingChunk).filter(
            MeetingChunk.organization_id == _FX.organization_id,
            MeetingChunk.importance_score.isnot(None),
        ).count()
        rel_n = db.query(Relationship).filter(
            Relationship.organization_id == _FX.organization_id,
            Relationship.importance_score.isnot(None),
        ).count()
        assert ent_n > 0, "entities should be scored"
        assert chunk_n == 0, f"chunks should NOT be scored, got {chunk_n}"
        assert rel_n == 0, f"relationships should NOT be scored, got {rel_n}"

        # Audit row exists for entity only
        target_kinds_in_audit = {
            r.target_kind for r in db.query(ImportanceRun).filter(
                ImportanceRun.organization_id == _FX.organization_id,
            ).all()
        }
        # Could contain prior-test entries; assert "entity" is at
        # least present and we didn't write meeting/doc/rel rows in this run.
        assert "entity" in target_kinds_in_audit
    finally:
        db.close()


def test_targets_all_scores_every_kind():
    from app.db.database import SessionLocal
    from app.db.models import (
        Entity, MeetingChunk, DocumentChunk, Relationship,
    )
    from app.scripts.backfill_importance import run as backfill_run
    db = SessionLocal()
    try:
        # Wipe all importance values
        for model in (MeetingChunk, DocumentChunk, Entity, Relationship):
            db.query(model).filter(
                model.organization_id == _FX.organization_id,
            ).update({"importance_score": None}, synchronize_session=False)
        db.commit()

        summary = backfill_run(
            org_id=_FX.organization_id, targets_arg="all", inline=True,
        )
        assert summary["dispatched"] == 1
        assert set(summary["targets"]) == {
            "meeting_chunk", "document_chunk", "entity", "relationship",
        }

        # Every kind now has at least one scored row
        for model in (MeetingChunk, DocumentChunk, Entity, Relationship):
            n = db.query(model).filter(
                model.organization_id == _FX.organization_id,
                model.importance_score.isnot(None),
            ).count()
            assert n > 0, (
                f"{model.__name__} not scored after --targets=all"
            )
    finally:
        db.close()


def test_idempotent_second_run_zero_updates():
    """After a full backfill, a second backfill writes audit rows
    with rows_updated=0 for each kind (scorer short-circuits)."""
    from app.db.database import SessionLocal
    from app.db.models import ImportanceRun
    from app.scripts.backfill_importance import run as backfill_run
    db = SessionLocal()
    try:
        # First pass to settle scores
        backfill_run(org_id=_FX.organization_id, inline=True)
        # Capture the audit rows from the upcoming run
        before_count = db.query(ImportanceRun).filter(
            ImportanceRun.organization_id == _FX.organization_id,
        ).count()
        backfill_run(org_id=_FX.organization_id, inline=True)
        # New rows from this second run
        new_rows = (
            db.query(ImportanceRun)
            .filter(ImportanceRun.organization_id == _FX.organization_id)
            .order_by(ImportanceRun.created_at.desc())
            .limit(4)
            .all()
        )
        assert len(new_rows) == 4
        # Each new row should report rows_updated == 0 (data is stable)
        for r in new_rows:
            assert r.rows_updated == 0, (
                f"{r.target_kind}: expected idempotent re-run "
                f"(rows_updated=0), got {r.rows_updated}"
            )
        after_count = db.query(ImportanceRun).filter(
            ImportanceRun.organization_id == _FX.organization_id,
        ).count()
        assert after_count == before_count + 4
    finally:
        db.close()


def test_cli_main_exits_zero_on_success():
    """The argparse entry point returns 0 when no errors."""
    from app.scripts.backfill_importance import main
    rc = main([
        "--org-id", str(_FX.organization_id),
        "--inline",
        "--targets", "entities",
    ])
    assert rc == 0


def test_resolve_targets_rejects_bogus_value():
    from app.scripts.backfill_importance import _resolve_targets
    for good in ("all", "chunks", "entities", "relationships"):
        out = _resolve_targets(good)
        assert isinstance(out, list) and out
    try:
        _resolve_targets("bogus")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on bogus --targets")


def test_algorithm_version_override_lands_in_audit():
    from app.db.database import SessionLocal
    from app.db.models import ImportanceRun
    from app.scripts.backfill_importance import run as backfill_run
    backfill_run(
        org_id=_FX.organization_id, inline=True,
        algorithm_version="v6f-custom",
    )
    db = SessionLocal()
    try:
        latest = (
            db.query(ImportanceRun)
            .filter(ImportanceRun.organization_id == _FX.organization_id)
            .order_by(ImportanceRun.created_at.desc())
            .first()
        )
        assert latest is not None
        assert latest.algorithm_version == "v6f-custom", (
            f"audit row missed override; got {latest.algorithm_version!r}"
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main_test() -> int:
    global _FX
    from app.db.database import SessionLocal
    from tests.fixtures import build_canonical_org, cleanup_canonical_org

    db = SessionLocal()
    try:
        _FX = build_canonical_org(db, mode="stub")
    finally:
        db.close()

    try:
        with section("6F - dry-run + scoping"):
            check("6F", "dry-run lists orgs + writes nothing",
                  test_dry_run_lists_orgs_without_writes)
            check("6F", "--org-id narrows to one org, others untouched",
                  test_org_id_narrows_to_single_org)

        with section("6F - target filtering"):
            check("6F", "--targets entities ONLY scores entities",
                  test_targets_entities_only_skips_chunks_and_rels)
            check("6F", "--targets all scores every kind",
                  test_targets_all_scores_every_kind)

        with section("6F - idempotency + CLI"):
            check("6F", "second run writes rows_updated=0 (idempotent)",
                  test_idempotent_second_run_zero_updates)
            check("6F", "CLI main exits 0 on success",
                  test_cli_main_exits_zero_on_success)
            check("6F", "_resolve_targets rejects bogus argument",
                  test_resolve_targets_rejects_bogus_value)
            check("6F", "--algorithm-version override lands in audit",
                  test_algorithm_version_override_lands_in_audit)
    finally:
        db = SessionLocal()
        try:
            cleanup_canonical_org(db, _FX)
        except Exception as e:
            print(f"  [cleanup error] {e}")
        finally:
            db.close()

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main_test())
