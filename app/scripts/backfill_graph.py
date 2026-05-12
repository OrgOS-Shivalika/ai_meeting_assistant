"""Phase 3E — graph extraction backfill.

Walks the `meetings` table for rows that should have a graph but don't —
either because they predate Phase 3 or because the latest successful
extraction used a stale prompt/model.

Eligibility (a meeting is "needs (re-)extraction" if ALL of these):
  - `meetings.status = 'completed'`               (transcript final)
  - `meetings.embedding_status = 'embedded'`      (chunks exist)
  - `meetings.transcript_raw IS NOT NULL`
  - one of:
      * `graph_status ∈ {pending, processing, failed}` (never produced)
      * the most recent successful `graph_extraction_runs` row for this
        meeting was made with a different `prompt_version` or `model`
        than the currently-configured one (prompt/model upgrade)

Usage:

    venv\\Scripts\\python.exe -m app.scripts.backfill_graph [flags]

Flags (mirror 2E for muscle memory):
    --org-id <uuid>            Restrict to one organization.
    --limit N                  Cap how many meetings we dispatch.
    --dry-run                  Print eligible ids and exit.
    --inline                   Run synchronously without Celery.
    --no-include-failed        Skip meetings with graph_status='failed'.
    --no-include-stale         Skip the prompt/model-upgrade re-extract path.

Idempotent. A second run after the first finishes finds zero eligible
meetings (until you bump `GRAPH_PROMPT_VERSION` or `GRAPH_EXTRACTION_MODEL`).
"""
from __future__ import annotations

import argparse
import logging
import sys
import uuid
from typing import Iterable, Optional

from sqlalchemy import text

from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import Meeting
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# Eligibility query — raw SQL because the latest-run-per-meeting check uses
# DISTINCT ON, which is awkward through SQLAlchemy expression language.
# ---------------------------------------------------------------------------

_SQL_ELIGIBLE = """
WITH latest_runs AS (
    SELECT DISTINCT ON (meeting_id)
        meeting_id, prompt_version, model
    FROM graph_extraction_runs
    WHERE status = 'completed'
    ORDER BY meeting_id,
             completed_at DESC NULLS LAST,
             created_at DESC
)
SELECT m.id
FROM meetings m
LEFT JOIN latest_runs lr ON lr.meeting_id = m.id
WHERE m.status = 'completed'
  AND m.embedding_status = 'embedded'
  AND m.transcript_raw IS NOT NULL
  AND (
        m.graph_status = ANY(:never_succeeded_states)
        {stale_branch}
  )
  {org_clause}
ORDER BY m.id ASC
{limit_clause}
"""


def _eligible_meeting_ids(
    db,
    *,
    org_id: uuid.UUID | None,
    include_failed: bool,
    include_stale: bool,
    current_prompt: str,
    current_model: str,
    limit: int | None,
) -> list[int]:
    states = ["pending", "processing"]
    if include_failed:
        states.append("failed")

    stale_branch = ""
    if include_stale:
        # `lr` is the latest *successful* run per meeting. If there isn't
        # one, the meeting falls into the never-succeeded branch already.
        # If there is one and its prompt/model differs from the active
        # config, that meeting is stale and re-eligible.
        stale_branch = (
            "OR (lr.meeting_id IS NOT NULL "
            "    AND (lr.prompt_version <> :current_prompt "
            "         OR lr.model <> :current_model))"
        )

    org_clause = "AND m.organization_id = :org_id" if org_id else ""
    limit_clause = "LIMIT :limit" if limit else ""

    sql = _SQL_ELIGIBLE.format(
        stale_branch=stale_branch,
        org_clause=org_clause,
        limit_clause=limit_clause,
    )
    params = {
        "never_succeeded_states": states,
        "current_prompt": current_prompt,
        "current_model": current_model,
    }
    if org_id is not None:
        params["org_id"] = org_id
    if limit is not None:
        params["limit"] = limit

    return [row[0] for row in db.execute(text(sql), params).all()]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _dispatch(
    meeting_ids: Iterable[int],
    *,
    inline: bool,
    extractor=None,
) -> tuple[int, int]:
    """Returns (ok_count, err_count). `inline=True` runs synchronously
    here; `False` enqueues `extract_graph.delay(id)`. `extractor` is
    only honored in the inline path — Celery doesn't pickle closures."""
    ok = 0
    err = 0
    if inline:
        from app.celery_tasks.graph_tasks import _extract_graph_sync
        for mid in meeting_ids:
            db = SessionLocal()
            try:
                meeting = db.query(Meeting).filter(Meeting.id == mid).first()
                if not meeting:
                    logger.warning("backfill_graph: meeting %s vanished mid-run", mid)
                    err += 1
                    continue
                result = _extract_graph_sync(db, meeting, extractor=extractor)
                logger.info(
                    "backfill_graph[inline] meeting=%s result=%s",
                    mid, result.get("status"),
                )
                if result.get("status") in ("extracted", "skipped"):
                    ok += 1
                else:
                    err += 1
            except Exception as e:
                logger.exception(
                    "backfill_graph[inline] meeting=%s crashed: %s", mid, e,
                )
                err += 1
            finally:
                db.close()
    else:
        from app.celery_tasks.graph_tasks import extract_graph
        for mid in meeting_ids:
            try:
                extract_graph.delay(mid)
                logger.info("backfill_graph[celery] dispatched meeting=%s", mid)
                ok += 1
            except Exception as e:
                logger.exception(
                    "backfill_graph[celery] dispatch failed for meeting=%s: %s",
                    mid, e,
                )
                err += 1
    return ok, err


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

def run(
    *,
    org_id: uuid.UUID | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    inline: bool = False,
    include_failed: bool = True,
    include_stale: bool = True,
    extractor=None,
) -> dict:
    """Programmatic entry point. Returns a summary dict suitable for
    introspection by tests and the CLI."""
    current_prompt = settings.GRAPH_PROMPT_VERSION
    current_model = settings.GRAPH_EXTRACTION_MODEL

    db = SessionLocal()
    try:
        ids = _eligible_meeting_ids(
            db,
            org_id=org_id,
            include_failed=include_failed,
            include_stale=include_stale,
            current_prompt=current_prompt,
            current_model=current_model,
            limit=limit,
        )
    finally:
        db.close()

    logger.info(
        "backfill_graph: eligible=%d (org=%s, include_failed=%s, include_stale=%s, "
        "prompt=%s, model=%s)",
        len(ids), org_id, include_failed, include_stale,
        current_prompt, current_model,
    )

    if dry_run or not ids:
        return {
            "eligible": len(ids),
            "meeting_ids": ids,
            "dispatched": 0,
            "errors": 0,
            "dry_run": dry_run,
            "inline": inline,
            "prompt_version": current_prompt,
            "model": current_model,
        }

    ok, err = _dispatch(ids, inline=inline, extractor=extractor)
    return {
        "eligible": len(ids),
        "meeting_ids": ids,
        "dispatched": ok,
        "errors": err,
        "dry_run": False,
        "inline": inline,
        "prompt_version": current_prompt,
        "model": current_model,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backfill_graph",
        description="Re-extract the knowledge graph for meetings that don't have "
                    "a current-prompt graph yet.",
    )
    p.add_argument("--org-id", type=str, default=None,
                   help="Restrict to one organization UUID.")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap on meetings dispatched in this run.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print eligible ids and exit without dispatching.")
    p.add_argument("--inline", action="store_true",
                   help="Run synchronously without Celery.")
    p.add_argument("--no-include-failed", dest="include_failed",
                   action="store_false",
                   help="Skip meetings with graph_status='failed'.")
    p.add_argument("--no-include-stale", dest="include_stale",
                   action="store_false",
                   help="Skip prompt/model-upgrade re-extract "
                        "(only re-extract never-succeeded meetings).")
    p.set_defaults(include_failed=True, include_stale=True)
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
        limit=args.limit,
        dry_run=args.dry_run,
        inline=args.inline,
        include_failed=args.include_failed,
        include_stale=args.include_stale,
    )

    print()
    print("=== backfill_graph summary ===")
    for k in ("eligible", "dispatched", "errors", "dry_run", "inline",
              "prompt_version", "model"):
        print(f"  {k}: {summary[k]}")
    if summary["dry_run"] and summary["meeting_ids"]:
        print("  meeting_ids:", summary["meeting_ids"])
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
