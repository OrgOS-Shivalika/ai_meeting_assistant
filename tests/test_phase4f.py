"""Phase 4F ship test — `backfill_documents` CLI.

Exercises the eligibility logic + the dispatch summary, without actually
hitting OpenAI or MinIO. We seed docs at every interesting status and
confirm the right ones are picked up by each (kind, stage) combination.

Coverage:

  1. Embedding eligibility: pending / processing / failed are picked up
     (failed only with --include-failed). 'embedded' and 'empty' are skipped.
  2. Embedding eligibility — stale branch: a doc whose chunks carry an
     older `embedding_model` is picked up with --include-stale.
  3. Graph eligibility: only embedded docs with pending/processing/failed
     graph_status. Docs that aren't yet embedded are skipped, even if
     their graph_status is 'pending'.
  4. --kind filter: category-only run never touches team docs.
  5. --limit caps per-kind, per-stage dispatch count.
  6. --org-id narrows to the requested org.
  7. dry_run returns ids without dispatching (no row changes).

We use dry_run for most cases — that's all the eligibility query path
needs to be exercised. Actual dispatch is end-to-end-tested in 4C/4D.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase4f.py
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
# Fixtures: many docs at every status the eligibility queries care about.
# ---------------------------------------------------------------------------

class _Fx:
    pass


def _mk_cat_doc(db, *, org_id, cat_id, user_id, name,
                emb_status="pending", graph_status="pending"):
    from app.db.models import CategoryDocument
    d = CategoryDocument(
        organization_id=org_id, category_id=cat_id, uploaded_by_user_id=user_id,
        name=name, original_filename=name,
        mime_type="application/pdf", size_bytes=10,
        storage_key=f"cat/{uuid.uuid4()}.pdf",
        status="uploaded",
        embedding_status=emb_status, graph_status=graph_status,
    )
    db.add(d); db.commit(); db.refresh(d)
    return d


def _mk_team_doc(db, *, org_id, team_id, user_id, name,
                 emb_status="pending", graph_status="pending"):
    from app.db.models import TeamDocument
    d = TeamDocument(
        organization_id=org_id, team_id=team_id, uploaded_by_user_id=user_id,
        name=name, original_filename=name,
        mime_type="application/pdf", size_bytes=10,
        storage_key=f"team/{uuid.uuid4()}.pdf",
        status="uploaded",
        embedding_status=emb_status, graph_status=graph_status,
    )
    db.add(d); db.commit(); db.refresh(d)
    return d


def _seed(db):
    from app.db.models import (
        Organization, User, Category, Team, DocumentChunk,
    )

    org = Organization(name="phase4f-org")
    other_org = Organization(name="phase4f-org-other")
    db.add_all([org, other_org]); db.commit()
    db.refresh(org); db.refresh(other_org)

    user = User(name="u", email=f"phase4f-{uuid.uuid4()}@example.com",
                password="x", organization_id=org.id)
    user_other = User(name="u2", email=f"phase4f-{uuid.uuid4()}@example.com",
                      password="x", organization_id=other_org.id)
    db.add_all([user, user_other]); db.commit()
    db.refresh(user); db.refresh(user_other)

    cat = Category(name="cat-4f", organization_id=org.id, user_id=user.id)
    cat_other = Category(name="cat-4f-other", organization_id=other_org.id,
                         user_id=user_other.id)
    db.add_all([cat, cat_other]); db.commit()
    db.refresh(cat); db.refresh(cat_other)

    team = Team(name="team-4f", category_id=cat.id)
    db.add(team); db.commit(); db.refresh(team)

    # Per-status category docs in primary org.
    cat_pending = _mk_cat_doc(db, org_id=org.id, cat_id=cat.id, user_id=user.id,
                              name="cat-pending.pdf", emb_status="pending")
    cat_processing = _mk_cat_doc(db, org_id=org.id, cat_id=cat.id, user_id=user.id,
                                 name="cat-processing.pdf", emb_status="processing")
    cat_failed = _mk_cat_doc(db, org_id=org.id, cat_id=cat.id, user_id=user.id,
                             name="cat-failed.pdf", emb_status="failed")
    cat_embedded = _mk_cat_doc(db, org_id=org.id, cat_id=cat.id, user_id=user.id,
                               name="cat-embedded.pdf", emb_status="embedded",
                               graph_status="extracted")
    cat_empty = _mk_cat_doc(db, org_id=org.id, cat_id=cat.id, user_id=user.id,
                            name="cat-empty.pdf", emb_status="empty",
                            graph_status="pending")

    # Two embedded cat docs with mismatched chunk model (stale branch).
    cat_stale = _mk_cat_doc(db, org_id=org.id, cat_id=cat.id, user_id=user.id,
                            name="cat-stale.pdf", emb_status="embedded",
                            graph_status="extracted")
    stale_chunk = DocumentChunk(
        organization_id=org.id, document_type="category",
        category_document_id=cat_stale.id, category_id=cat.id,
        chunk_index=0, text="stale chunk", token_count=2,
        embedding=[0.0] * 1536,
        embedding_model="OLD-MODEL-NAME",
    )
    db.add(stale_chunk); db.commit()

    # Docs that need a graph re-run (embedded but graph still pending/failed).
    cat_embedded_graph_pending = _mk_cat_doc(
        db, org_id=org.id, cat_id=cat.id, user_id=user.id,
        name="cat-graph-pending.pdf",
        emb_status="embedded", graph_status="pending",
    )
    cat_embedded_graph_failed = _mk_cat_doc(
        db, org_id=org.id, cat_id=cat.id, user_id=user.id,
        name="cat-graph-failed.pdf",
        emb_status="embedded", graph_status="failed",
    )
    # A NOT-embedded doc with graph_status=pending — must NOT be graph-eligible.
    cat_unembedded_graph_pending = _mk_cat_doc(
        db, org_id=org.id, cat_id=cat.id, user_id=user.id,
        name="cat-not-embedded-graph-pending.pdf",
        emb_status="pending", graph_status="pending",
    )

    # Team docs.
    team_pending = _mk_team_doc(db, org_id=org.id, team_id=team.id, user_id=user.id,
                                name="team-pending.docx", emb_status="pending")
    team_embedded = _mk_team_doc(db, org_id=org.id, team_id=team.id, user_id=user.id,
                                 name="team-embedded.docx", emb_status="embedded",
                                 graph_status="extracted")

    # Other-org doc (should never appear when org_id is set).
    cat_other_pending = _mk_cat_doc(
        db, org_id=other_org.id, cat_id=cat_other.id, user_id=user_other.id,
        name="other-org-pending.pdf", emb_status="pending",
    )

    fx = _Fx()
    fx.org_id = org.id
    fx.other_org_id = other_org.id
    fx.user_id = user.id
    fx.cat_id = cat.id
    fx.team_id = team.id
    # Cat embedding-eligible (pending/processing/failed/stale): 4 docs +
    #   the 2 graph-only ones don't count (they're 'embedded') +
    #   the unembedded_graph_pending counts (status=pending).
    fx.cat_pending = cat_pending.id
    fx.cat_processing = cat_processing.id
    fx.cat_failed = cat_failed.id
    fx.cat_embedded = cat_embedded.id
    fx.cat_empty = cat_empty.id
    fx.cat_stale = cat_stale.id
    fx.cat_embedded_graph_pending = cat_embedded_graph_pending.id
    fx.cat_embedded_graph_failed = cat_embedded_graph_failed.id
    fx.cat_unembedded_graph_pending = cat_unembedded_graph_pending.id
    fx.team_pending = team_pending.id
    fx.team_embedded = team_embedded.id
    fx.cat_other_pending = cat_other_pending.id
    return fx


def _cleanup(db, fx):
    from sqlalchemy import text
    db.execute(text("DELETE FROM document_chunks WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM document_chunks WHERE organization_id = :o"),
               {"o": fx.other_org_id})
    db.execute(text("DELETE FROM team_documents WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM category_documents WHERE organization_id = :o"),
               {"o": fx.org_id})
    db.execute(text("DELETE FROM category_documents WHERE organization_id = :o"),
               {"o": fx.other_org_id})
    db.execute(text("DELETE FROM teams WHERE category_id = :c"),
               {"c": fx.cat_id})
    db.execute(text("DELETE FROM categories WHERE organization_id IN (:a, :b)"),
               {"a": fx.org_id, "b": fx.other_org_id})
    db.execute(text("DELETE FROM users WHERE organization_id IN (:a, :b)"),
               {"a": fx.org_id, "b": fx.other_org_id})
    db.execute(text("DELETE FROM organizations WHERE id IN (:a, :b)"),
               {"a": fx.org_id, "b": fx.other_org_id})
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX: _Fx | None = None


def test_embedding_eligibility_picks_failed_and_pending():
    from app.scripts.backfill_documents import run
    summary = run(
        kinds=["category"], stages=["embedding"],
        org_id=_FX.org_id, dry_run=True,
        include_failed=True, include_stale=False,
    )
    ids = set(summary["by_stage"]["embedding"]["category"]["doc_ids"])
    # Expected eligible cat-embedding (no stale): pending, processing,
    # failed, and the unembedded-graph-pending one (its emb_status='pending').
    expected = {
        str(_FX.cat_pending),
        str(_FX.cat_processing),
        str(_FX.cat_failed),
        str(_FX.cat_unembedded_graph_pending),
    }
    assert ids == expected, f"got {ids}, expected {expected}"


def test_no_include_failed_excludes_failed():
    from app.scripts.backfill_documents import run
    summary = run(
        kinds=["category"], stages=["embedding"],
        org_id=_FX.org_id, dry_run=True,
        include_failed=False, include_stale=False,
    )
    ids = set(summary["by_stage"]["embedding"]["category"]["doc_ids"])
    assert str(_FX.cat_failed) not in ids
    assert str(_FX.cat_pending) in ids


def test_include_stale_picks_old_model():
    from app.scripts.backfill_documents import run
    summary = run(
        kinds=["category"], stages=["embedding"],
        org_id=_FX.org_id, dry_run=True,
        include_failed=False, include_stale=True,
    )
    ids = set(summary["by_stage"]["embedding"]["category"]["doc_ids"])
    # cat_stale is 'embedded' so it'd be excluded without --include-stale,
    # but its chunks point at OLD-MODEL-NAME so the stale branch picks it up.
    assert str(_FX.cat_stale) in ids


def test_graph_eligibility_requires_embedded():
    from app.scripts.backfill_documents import run
    summary = run(
        kinds=["category"], stages=["graph"],
        org_id=_FX.org_id, dry_run=True,
        include_failed=True,
    )
    ids = set(summary["by_stage"]["graph"]["category"]["doc_ids"])
    # Eligible: embedded + (pending|failed) graph_status.
    expected = {
        str(_FX.cat_embedded_graph_pending),
        str(_FX.cat_embedded_graph_failed),
    }
    assert ids == expected, f"got {ids}, expected {expected}"
    # NOT eligible: the unembedded one, even though graph_status='pending'.
    assert str(_FX.cat_unembedded_graph_pending) not in ids
    # NOT eligible: the embedded docs whose graph_status='extracted'.
    assert str(_FX.cat_embedded) not in ids


def test_kind_filter_excludes_other_table():
    from app.scripts.backfill_documents import run
    cat_only = run(
        kinds=["category"], stages=["embedding"],
        org_id=_FX.org_id, dry_run=True,
    )
    assert "team" not in cat_only["by_stage"]["embedding"]

    team_only = run(
        kinds=["team"], stages=["embedding"],
        org_id=_FX.org_id, dry_run=True,
    )
    assert "category" not in team_only["by_stage"]["embedding"]
    ids = set(team_only["by_stage"]["embedding"]["team"]["doc_ids"])
    assert str(_FX.team_pending) in ids
    assert str(_FX.team_embedded) not in ids


def test_limit_caps_per_kind_stage():
    from app.scripts.backfill_documents import run
    summary = run(
        kinds=["category"], stages=["embedding"],
        org_id=_FX.org_id, dry_run=True, limit=2,
    )
    ids = summary["by_stage"]["embedding"]["category"]["doc_ids"]
    assert len(ids) <= 2


def test_org_id_narrows_results():
    from app.scripts.backfill_documents import run
    summary = run(
        kinds=["category"], stages=["embedding"],
        org_id=_FX.org_id, dry_run=True, include_stale=False,
    )
    ids = set(summary["by_stage"]["embedding"]["category"]["doc_ids"])
    assert str(_FX.cat_other_pending) not in ids, "other-org doc leaked in"


def test_dry_run_makes_no_changes():
    """Dry run should never increment dispatched counts and never touch
    any document row's status."""
    from app.db.database import SessionLocal
    from app.db.models import CategoryDocument
    from app.scripts.backfill_documents import run

    db = SessionLocal()
    try:
        before = db.query(CategoryDocument).filter(
            CategoryDocument.id == _FX.cat_pending,
        ).first()
        before_status = before.embedding_status
        before_msg = before.error_message
    finally:
        db.close()

    summary = run(
        kinds=["category", "team"], stages=["embedding", "graph"],
        org_id=_FX.org_id, dry_run=True,
    )
    assert summary["total_dispatched"] == 0
    assert summary["total_errors"] == 0
    assert summary["total_eligible"] > 0

    db = SessionLocal()
    try:
        after = db.query(CategoryDocument).filter(
            CategoryDocument.id == _FX.cat_pending,
        ).first()
        assert after.embedding_status == before_status
        assert after.error_message == before_msg
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    global _FX
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        _FX = _seed(db)
    finally:
        db.close()

    try:
        with section("4F - backfill_documents CLI eligibility"):
            check("4F", "embedding: picks pending+processing+failed",
                  test_embedding_eligibility_picks_failed_and_pending)
            check("4F", "embedding: --no-include-failed excludes 'failed'",
                  test_no_include_failed_excludes_failed)
            check("4F", "embedding: --include-stale catches model-upgrade",
                  test_include_stale_picks_old_model)
            check("4F", "graph: only embedded docs with pending/failed graph",
                  test_graph_eligibility_requires_embedded)
            check("4F", "--kind filter excludes the other doc table",
                  test_kind_filter_excludes_other_table)
            check("4F", "--limit caps per (kind, stage)",
                  test_limit_caps_per_kind_stage)
            check("4F", "--org-id narrows to single org",
                  test_org_id_narrows_results)
            check("4F", "dry_run makes no DB writes, no dispatches",
                  test_dry_run_makes_no_changes)
    finally:
        db = SessionLocal()
        try:
            _cleanup(db, _FX)
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
    sys.exit(main())
