"""Phase 6F — importance backfill CLI.

Walks every active org and runs `score_org()` over the requested
target kinds. Mirrors the shape of `backfill_embeddings.py` (Phase 2E),
`backfill_graph.py` (Phase 3E), and `backfill_documents.py` (Phase 4F)
so the operator UX is consistent across phases.

Usage:

    venv\\Scripts\\python.exe -m app.scripts.backfill_importance [flags]

Flags:
    --org-id <uuid>             Restrict to one org. Default: all orgs.
    --targets chunks|entities|relationships|all
                                Which target kinds to score. Default: all.
                                (`chunks` covers both meeting + document.)
    --inline                    Run sync in this process. Default
                                routes to Celery when settings.USE_CELERY.
    --dry-run                   List eligible orgs + target kinds and
                                exit without scoring anything.
    --limit N                   Cap on orgs dispatched.
    --algorithm-version v1      Override settings.IMPORTANCE_ALGORITHM_VERSION.

Exit codes: 0 on success (incl. dry-run), 1 if any org's scoring
returned `status='failed'`.

Idempotent. Re-running over data that hasn't changed produces
`rows_updated=0` for each (org, target_kind) batch — the scorer
already short-circuits on within-epsilon scores.
"""
from __future__ import annotations

import argparse
import logging
import sys
import uuid
from typing import Iterable, Literal

from sqlalchemy import select

from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import ImportanceRun, Organization
from app.services.importance import score_org
from app.services.importance.scorer import ImportanceWeights, TargetKind
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# Target translation
# ---------------------------------------------------------------------------

def _resolve_targets(arg: str) -> list[TargetKind]:
    """`--targets chunks` -> meeting + document chunks; the alias is
    just a UX convenience so users don't have to remember the
    underscored kind names."""
    if arg == "all":
        return ["meeting_chunk", "document_chunk", "entity", "relationship"]
    if arg == "chunks":
        return ["meeting_chunk", "document_chunk"]
    if arg == "entities":
        return ["entity"]
    if arg == "relationships":
        return ["relationship"]
    raise ValueError(
        f"--targets must be one of: all, chunks, entities, relationships "
        f"(got {arg!r})"
    )


# ---------------------------------------------------------------------------
# Eligible-org enumerator
# ---------------------------------------------------------------------------

def _eligible_org_ids(
    *, org_id: uuid.UUID | None, limit: int | None,
) -> list[uuid.UUID]:
    db = SessionLocal()
    try:
        stmt = select(Organization.id).order_by(Organization.created_at.asc())
        if org_id is not None:
            stmt = stmt.where(Organization.id == org_id)
        if limit is not None:
            stmt = stmt.limit(limit)
        return [row[0] for row in db.execute(stmt).all()]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Dispatchers
# ---------------------------------------------------------------------------

def _score_inline(
    org_ids: Iterable[uuid.UUID], *,
    targets: list[TargetKind], weights: ImportanceWeights | None,
) -> tuple[int, int]:
    """Run scoring sync in this process. Returns (ok_orgs, err_orgs).
    Each org gets its own DB session so a single crash doesn't poison
    the next org."""
    ok = err = 0
    for oid in org_ids:
        db = SessionLocal()
        try:
            results = score_org(
                db, organization_id=oid, weights=weights, targets=targets,
            )
            # Detect at least one failed target_kind in the audit rows.
            statuses = {}
            for kind, run_id in results.items():
                row = db.query(ImportanceRun).filter(
                    ImportanceRun.id == run_id
                ).first()
                statuses[kind] = row.status if row else "unknown"
            if all(s == "completed" for s in statuses.values()):
                ok += 1
                logger.info(
                    "backfill[inline] org=%s targets=%s OK", oid, list(statuses.keys()),
                )
            else:
                err += 1
                logger.error(
                    "backfill[inline] org=%s mixed statuses: %s", oid, statuses,
                )
        except Exception as e:
            err += 1
            logger.exception("backfill[inline] org=%s crashed: %s", oid, e)
        finally:
            db.close()
    return ok, err


def _score_via_celery(org_ids: Iterable[uuid.UUID]) -> tuple[int, int]:
    """Dispatch one Celery task per org via the existing 6A wrapper.
    NOTE: a Celery dispatch is fire-and-forget — `ok` here means the
    enqueue succeeded, not that the score eventually succeeded."""
    from app.celery_tasks.importance_tasks import score_org_task
    ok = err = 0
    for oid in org_ids:
        try:
            score_org_task.delay(str(oid))
            ok += 1
            logger.info("backfill[celery] dispatched org=%s", oid)
        except Exception as e:
            err += 1
            logger.exception("backfill[celery] dispatch failed for org=%s: %s", oid, e)
    return ok, err


# ---------------------------------------------------------------------------
# Programmatic entry — used by tests + the CLI
# ---------------------------------------------------------------------------

def run(
    *,
    org_id: uuid.UUID | None = None,
    targets_arg: str = "all",
    inline: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
    algorithm_version: str | None = None,
) -> dict:
    """Same semantics as the CLI. Returns a summary dict that the
    test harness + dashboards can introspect."""
    targets = _resolve_targets(targets_arg)
    weights = ImportanceWeights.from_settings()
    if algorithm_version:
        # Build a fresh weights bundle with the override (frozen dataclass)
        weights = ImportanceWeights(
            **{**weights.as_dict(),
               "algorithm_version": algorithm_version},
        )
    org_ids = _eligible_org_ids(org_id=org_id, limit=limit)
    if dry_run or not org_ids:
        return {
            "eligible_orgs": len(org_ids),
            "org_ids": [str(o) for o in org_ids],
            "dispatched": 0,
            "errors": 0,
            "dry_run": dry_run,
            "inline": inline,
            "targets": targets,
            "algorithm_version": weights.algorithm_version,
        }
    # Celery path doesn't honor per-target filtering — the worker
    # always scores all four kinds. For partial-target runs use --inline.
    if inline or targets_arg != "all":
        ok, err = _score_inline(org_ids, targets=targets, weights=weights)
        return {
            "eligible_orgs": len(org_ids),
            "org_ids": [str(o) for o in org_ids],
            "dispatched": ok,
            "errors": err,
            "dry_run": False,
            "inline": True,
            "targets": targets,
            "algorithm_version": weights.algorithm_version,
        }
    # Celery fanout
    ok, err = _score_via_celery(org_ids)
    return {
        "eligible_orgs": len(org_ids),
        "org_ids": [str(o) for o in org_ids],
        "dispatched": ok,
        "errors": err,
        "dry_run": False,
        "inline": False,
        "targets": targets,
        "algorithm_version": weights.algorithm_version,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backfill_importance",
        description="Score importance for every active org's knowledge tier.",
    )
    p.add_argument("--org-id", type=str, default=None,
                   help="Restrict to one organization UUID.")
    p.add_argument("--targets",
                   choices=["all", "chunks", "entities", "relationships"],
                   default="all",
                   help="Which target kinds to score. Default: all.")
    p.add_argument("--inline", action="store_true",
                   help="Run synchronously in this process (skip Celery).")
    p.add_argument("--dry-run", action="store_true",
                   help="List eligible orgs and exit.")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap on orgs dispatched in this run.")
    p.add_argument("--algorithm-version", type=str, default=None,
                   help="Override IMPORTANCE_ALGORITHM_VERSION for this run.")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.getLogger().setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    logging.getLogger().addHandler(handler)

    args = _build_parser().parse_args(argv)
    org_id = uuid.UUID(args.org_id) if args.org_id else None
    summary = run(
        org_id=org_id,
        targets_arg=args.targets,
        inline=args.inline,
        dry_run=args.dry_run,
        limit=args.limit,
        algorithm_version=args.algorithm_version,
    )

    print()
    print("=== backfill_importance summary ===")
    print(f"  eligible_orgs:     {summary['eligible_orgs']}")
    print(f"  dispatched:        {summary['dispatched']}")
    print(f"  errors:            {summary['errors']}")
    print(f"  inline:            {summary['inline']}")
    print(f"  dry_run:           {summary['dry_run']}")
    print(f"  targets:           {summary['targets']}")
    print(f"  algorithm_version: {summary['algorithm_version']}")
    if summary["dry_run"] and summary["org_ids"]:
        print("  org_ids:")
        for oid in summary["org_ids"]:
            print(f"    {oid}")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
