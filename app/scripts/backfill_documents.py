"""Phase 4F — document ingestion backfill.

Walks `category_documents` + `team_documents` for rows that should have
chunks or a graph but don't, and dispatches the right Celery task for
each. Mirrors `backfill_embeddings.py` (Phase 2E) in shape so anyone who
has run that one can drive this one.

Eligibility rules:

  - **Embedding stage** (`--stage=embedding`): docs whose
    `embedding_status` is one of {pending, processing, failed} —
    `failed` only if `--include-failed`. Plus, with `--include-stale`,
    docs that succeeded earlier but under a different
    `EMBEDDING_MODEL` than the current one (model-upgrade re-embed,
    detected via EXISTS on `document_chunks`).

  - **Graph stage** (`--stage=graph`): docs whose
    `embedding_status='embedded'` AND `graph_status` in
    {pending, processing, failed (if `--include-failed`)}. We never
    dispatch graph for docs that haven't been embedded yet — the doc
    graph pipeline pre-checks the same invariant.

  - **`--stage=both`** (default): does embedding-eligible first; the
    ingest task auto-fans out to graph extraction afterward. Docs that
    only need a graph re-run (already embedded but graph stuck) are
    picked up by the graph pass that runs after the embedding pass.

Usage:

    venv\\Scripts\\python.exe -m app.scripts.backfill_documents [flags]

Flags:
    --kind <category|team|both>     Which doc table(s). Default: both.
    --stage <embedding|graph|both>  Pipeline stage. Default: both.
    --org-id <uuid>                 Restrict to one organization.
    --limit N                       Cap dispatched docs per kind+stage.
    --dry-run                       Print eligible ids and exit.
    --inline                        Run synchronously (no Celery broker).
    --no-include-failed             Skip 'failed' embedding/graph rows.
    --no-include-stale              Skip model-upgrade re-embed.

Exit codes: 0 on success (incl. dry-run), 1 if any dispatch raised.

Idempotent. The ingest sync function wipes-and-reinserts chunks; the
graph sync function upserts entities with version bumps. A second run
that overlaps the first will see fewer eligible docs but won't corrupt
any rows.
"""
from __future__ import annotations

import argparse
import logging
import sys
import uuid
from typing import Iterable, Literal

from sqlalchemy import exists, or_, select

from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import (
    CategoryDocument, DocumentChunk, TeamDocument,
)
from app.utils.logger import setup_logger
from app.utils.enums import EmbeddingStatus, GraphStatus

logger = setup_logger(__name__)

DocKind = Literal["category", "team"]
Stage = Literal["embedding", "graph"]


# ---------------------------------------------------------------------------
# Eligibility queries
# ---------------------------------------------------------------------------

def _doc_model(kind: DocKind):
    return CategoryDocument if kind == "category" else TeamDocument


def _chunks_parent_col(kind: DocKind):
    return (
        DocumentChunk.category_document_id
        if kind == "category"
        else DocumentChunk.team_document_id
    )


def _eligible_for_embedding(
    db,
    kind: DocKind,
    *,
    org_id: uuid.UUID | None,
    include_failed: bool,
    include_stale: bool,
    current_model: str,
    limit: int | None,
) -> list[str]:
    Doc = _doc_model(kind)

    branches = []
    never_succeeded_states = [EmbeddingStatus.PENDING, EmbeddingStatus.PROCESSING]
    if include_failed:
        never_succeeded_states.append(EmbeddingStatus.FAILED)
    branches.append(Doc.embedding_status.in_(never_succeeded_states))

    if include_stale:
        parent_col = _chunks_parent_col(kind)
        stale_predicate = exists(
            select(1).where(
                parent_col == Doc.id,
                DocumentChunk.embedding_model != current_model,
            )
        )
        branches.append(stale_predicate)

    stmt = (
        select(Doc.id)
        .where(or_(*branches))
        .order_by(Doc.created_at.asc())
    )
    if org_id is not None:
        stmt = stmt.where(Doc.organization_id == org_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return [str(row[0]) for row in db.execute(stmt).all()]


def _eligible_for_graph(
    db,
    kind: DocKind,
    *,
    org_id: uuid.UUID | None,
    include_failed: bool,
    limit: int | None,
) -> list[str]:
    Doc = _doc_model(kind)
    graph_states = [GraphStatus.PENDING, GraphStatus.PROCESSING]
    if include_failed:
        graph_states.append(GraphStatus.FAILED)

    stmt = (
        select(Doc.id)
        .where(
            Doc.embedding_status == EmbeddingStatus.EMBEDDED,
            Doc.graph_status.in_(graph_states),
        )
        .order_by(Doc.created_at.asc())
    )
    if org_id is not None:
        stmt = stmt.where(Doc.organization_id == org_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return [str(row[0]) for row in db.execute(stmt).all()]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _dispatch_embedding(
    kind: DocKind, doc_ids: Iterable[str], *, inline: bool,
) -> tuple[int, int]:
    ok = err = 0
    if inline:
        from app.celery_tasks.document_ingest import _ingest_document_sync
        for did in doc_ids:
            db = SessionLocal()
            try:
                result = _ingest_document_sync(db, kind, did)
                logger.info(
                    "backfill[inline,embed,%s] doc=%s status=%s",
                    kind, did, result.get("status"),
                )
                if result.get("status") in ("embedded", "empty", "skipped"):
                    ok += 1
                else:
                    err += 1
            except Exception as e:
                logger.exception(
                    "backfill[inline,embed,%s] doc=%s crashed: %s", kind, did, e,
                )
                err += 1
            finally:
                db.close()
    else:
        if kind == "category":
            from app.celery_tasks.document_tasks import process_document as _task
        else:
            from app.celery_tasks.team_document_tasks import process_team_document as _task
        for did in doc_ids:
            try:
                _task.delay(did)
                logger.info("backfill[celery,embed,%s] dispatched doc=%s", kind, did)
                ok += 1
            except Exception as e:
                logger.exception(
                    "backfill[celery,embed,%s] dispatch failed for doc=%s: %s",
                    kind, did, e,
                )
                err += 1
    return ok, err


def _dispatch_graph(
    kind: DocKind, doc_ids: Iterable[str], *, inline: bool,
) -> tuple[int, int]:
    ok = err = 0
    if inline:
        from app.celery_tasks.document_graph_tasks import (
            _extract_graph_for_document_sync,
        )
        for did in doc_ids:
            db = SessionLocal()
            try:
                Doc = _doc_model(kind)
                doc = db.query(Doc).filter(Doc.id == did).first()
                if not doc:
                    logger.warning(
                        "backfill[inline,graph,%s] doc %s vanished mid-run",
                        kind, did,
                    )
                    err += 1
                    continue
                result = _extract_graph_for_document_sync(db, kind, doc)
                logger.info(
                    "backfill[inline,graph,%s] doc=%s status=%s",
                    kind, did, result.get("status"),
                )
                if result.get("status") in ("extracted", "skipped"):
                    ok += 1
                else:
                    err += 1
            except Exception as e:
                logger.exception(
                    "backfill[inline,graph,%s] doc=%s crashed: %s", kind, did, e,
                )
                err += 1
            finally:
                db.close()
    else:
        from app.celery_tasks.document_graph_tasks import extract_document_graph
        for did in doc_ids:
            try:
                extract_document_graph.delay(kind, did)
                logger.info("backfill[celery,graph,%s] dispatched doc=%s", kind, did)
                ok += 1
            except Exception as e:
                logger.exception(
                    "backfill[celery,graph,%s] dispatch failed for doc=%s: %s",
                    kind, did, e,
                )
                err += 1
    return ok, err


# ---------------------------------------------------------------------------
# Programmatic entry point — used by tests and the CLI.
# ---------------------------------------------------------------------------

def run(
    *,
    kinds: list[DocKind] | None = None,
    stages: list[Stage] | None = None,
    org_id: uuid.UUID | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    inline: bool = False,
    include_failed: bool = True,
    include_stale: bool = True,
) -> dict:
    """Same semantics as the CLI. Returns a summary dict keyed by stage."""
    kinds = kinds or ["category", "team"]
    stages = stages or ["embedding", "graph"]
    current_model = settings.EMBEDDING_MODEL

    summary: dict = {
        "dry_run": dry_run, "inline": inline,
        "model": current_model,
        "by_stage": {},
        "total_eligible": 0,
        "total_dispatched": 0,
        "total_errors": 0,
    }

    for stage in stages:
        by_kind: dict = {}
        for kind in kinds:
            db = SessionLocal()
            try:
                if stage == "embedding":
                    ids = _eligible_for_embedding(
                        db, kind,
                        org_id=org_id,
                        include_failed=include_failed,
                        include_stale=include_stale,
                        current_model=current_model,
                        limit=limit,
                    )
                else:
                    ids = _eligible_for_graph(
                        db, kind,
                        org_id=org_id,
                        include_failed=include_failed,
                        limit=limit,
                    )
            finally:
                db.close()

            logger.info(
                "backfill[%s,%s]: eligible=%d (org=%s)",
                stage, kind, len(ids), org_id,
            )
            entry = {
                "eligible": len(ids),
                "doc_ids": ids,
                "dispatched": 0,
                "errors": 0,
            }
            if not dry_run and ids:
                if stage == "embedding":
                    ok, err = _dispatch_embedding(kind, ids, inline=inline)
                else:
                    ok, err = _dispatch_graph(kind, ids, inline=inline)
                entry["dispatched"] = ok
                entry["errors"] = err
            by_kind[kind] = entry
            summary["total_eligible"] += entry["eligible"]
            summary["total_dispatched"] += entry["dispatched"]
            summary["total_errors"] += entry["errors"]
        summary["by_stage"][stage] = by_kind

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backfill_documents",
        description="Embed + graph-extract documents that don't have AI memory yet.",
    )
    p.add_argument("--kind", choices=["category", "team", "both"], default="both",
                   help="Which doc table(s) to backfill. Default: both.")
    p.add_argument("--stage", choices=["embedding", "graph", "both"], default="both",
                   help="Which pipeline stage to run. Default: both.")
    p.add_argument("--org-id", type=str, default=None,
                   help="Restrict to one organization UUID.")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap docs dispatched per (kind, stage).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print eligible ids and exit without dispatching.")
    p.add_argument("--inline", action="store_true",
                   help="Run synchronously without Celery.")
    p.add_argument("--no-include-failed", dest="include_failed", action="store_false",
                   help="Skip docs with failed embedding_status / graph_status.")
    p.add_argument("--no-include-stale", dest="include_stale", action="store_false",
                   help="Skip model-upgrade re-embed branch.")
    p.set_defaults(include_failed=True, include_stale=True)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.getLogger().setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(handler)

    args = _build_parser().parse_args(argv)
    kinds: list[DocKind] = (
        ["category", "team"] if args.kind == "both" else [args.kind]
    )
    stages: list[Stage] = (
        ["embedding", "graph"] if args.stage == "both" else [args.stage]
    )
    org_id = uuid.UUID(args.org_id) if args.org_id else None

    summary = run(
        kinds=kinds, stages=stages,
        org_id=org_id, limit=args.limit,
        dry_run=args.dry_run, inline=args.inline,
        include_failed=args.include_failed,
        include_stale=args.include_stale,
    )

    print()
    print("=== backfill_documents summary ===")
    print(f"  dry_run: {summary['dry_run']}")
    print(f"  inline:  {summary['inline']}")
    print(f"  model:   {summary['model']}")
    print(f"  total_eligible:   {summary['total_eligible']}")
    print(f"  total_dispatched: {summary['total_dispatched']}")
    print(f"  total_errors:     {summary['total_errors']}")
    for stage, by_kind in summary["by_stage"].items():
        print(f"  [{stage}]")
        for kind, entry in by_kind.items():
            print(
                f"    {kind:9s}  eligible={entry['eligible']:4d}  "
                f"dispatched={entry['dispatched']:4d}  errors={entry['errors']:4d}"
            )
            if summary["dry_run"] and entry["doc_ids"]:
                print(f"               ids: {entry['doc_ids']}")
    return 1 if summary["total_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
